package corpus

import (
	"math/big"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"testing"
)

func item(sku string, qty int64, price string) RawItem {
	return RawItem{Sku: sku, Qty: qty, Price: price}
}
func request(rows []RawItem, tier, coupon, region string) Request {
	return Request{Items: rows, Tier: tier, Coupon: coupon, Region: region}
}
func fail(code string, index *int) Outcome {
	return Outcome{Err: &QuoteError{Code: code, Index: index}}
}
func priceText(cents int64) string {
	whole := strconv.FormatInt(cents/100, 10)
	fraction := strconv.FormatInt(cents%100+100, 10)[1:]
	return whole + "." + fraction
}
func at(index int) *int { return &index }
func expected(
	lines []Line,
	subtotal, tier, coupon, shipping, tax, total int64,
	applied ...string,
) Outcome {
	return Outcome{Quote: &Quote{
		Lines: lines, Subtotal: subtotal, TierDiscount: tier,
		CouponDiscount: coupon, Shipping: shipping, Tax: tax,
		Total: total, Applied: applied,
	}}
}

var skuPattern = regexp.MustCompile(`^[A-Z0-9-]{3,12}$`)
var pricePattern = regexp.MustCompile(`^[0-9]{1,6}(\.[0-9]{1,2})?$`)

func refCents(text string) (int64, bool) {
	if !pricePattern.MatchString(text) {
		return 0, false
	}
	parts := strings.Split(text, ".")
	whole, _ := strconv.ParseInt(parts[0], 10, 64)
	fraction := ""
	if len(parts) == 2 {
		fraction = parts[1]
	}
	fraction += strings.Repeat("0", 2-len(fraction))
	frac := int64(0)
	if fraction != "" {
		frac, _ = strconv.ParseInt(fraction, 10, 64)
	}
	cents := whole*100 + frac
	return cents, cents > 0
}
func roundBig(n, d int64) int64 {
	numerator := big.NewInt(n)
	denominator := big.NewInt(d)
	q, r := new(big.Int), new(big.Int)
	q.QuoRem(numerator, denominator, r)
	if new(big.Int).Lsh(r, 1).Cmp(denominator) >= 0 {
		q.Add(q, big.NewInt(1))
	}
	return q.Int64()
}

type splitMix64 struct{ state uint64 }

func (r *splitMix64) next() uint64 {
	r.state += 0x9e3779b97f4a7c15
	z := r.state
	z = (z ^ (z >> 30)) * 0xbf58476d1ce4e5b9
	z = (z ^ (z >> 27)) * 0x94d049bb133111eb
	return z ^ (z >> 31)
}
func oracle(g Request) Outcome {
	if len(g.Items) == 0 {
		return fail("EMPTY_ORDER", nil)
	}
	if len(g.Items) > 50 {
		return fail("TOO_MANY_ITEMS", nil)
	}
	type row struct {
		sku        string
		qty, cents int64
	}
	rows := make([]row, 0, len(g.Items))
	for i, raw := range g.Items {
		s := strings.ToUpper(strings.TrimSpace(raw.Sku))
		if !skuPattern.MatchString(s) {
			return fail("BAD_SKU", at(i))
		}
		if raw.Qty < 1 || raw.Qty > 1000 {
			return fail("BAD_QTY", at(i))
		}
		cents, ok := refCents(raw.Price)
		if !ok {
			return fail("BAD_PRICE", at(i))
		}
		rows = append(rows, row{s, raw.Qty, cents})
	}
	merged := map[string]row{}
	for i, r := range rows {
		old, ok := merged[r.sku]
		if ok {
			if old.cents != r.cents {
				return fail("PRICE_CONFLICT", at(i))
			}
			old.qty += r.qty
			if old.qty > 1000 {
				return fail("BAD_QTY", at(i))
			}
			merged[r.sku] = old
		} else {
			merged[r.sku] = r
		}
	}
	tier := strings.ToLower(strings.TrimSpace(g.Tier))
	coupon := strings.ToUpper(strings.TrimSpace(g.Coupon))
	region := strings.ToUpper(strings.TrimSpace(g.Region))
	tierBP := int64(0)
	switch tier {
	case "basic":
	case "silver":
		tierBP = 500
	case "gold":
		tierBP = 1000
	default:
		return fail("BAD_TIER", nil)
	}
	if coupon != "" && coupon != "FREESHIP" {
		good := false
		for _, p := range []string{"PCT", "FIXED"} {
			if strings.HasPrefix(coupon, p) {
				n, e := strconv.Atoi(strings.TrimPrefix(coupon, p))
				limit := 50
				if p == "FIXED" {
					limit = 500
				}
				good = e == nil && n >= 1 && n <= limit && strconv.Itoa(n) == strings.TrimPrefix(coupon, p)
			}
		}
		if !good {
			return fail("BAD_COUPON", nil)
		}
	}
	taxBP, ship, threshold := int64(0), int64(0), int64(0)
	switch region {
	case "EU":
		taxBP, ship, threshold = 2000, 800, 10000
	case "US":
		taxBP, ship, threshold = 700, 500, 7500
	case "ASIA":
		taxBP, ship, threshold = 1000, 1200, 15000
	default:
		return fail("BAD_REGION", nil)
	}
	keys := make([]string, 0, len(merged))
	for k := range merged {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	lines := make([]Line, 0, len(keys))
	var subtotal int64
	for _, k := range keys {
		r := merged[k]
		lc := r.qty * r.cents
		lines = append(lines, Line{Sku: k, Qty: r.qty, UnitCents: r.cents, LineCents: lc})
		subtotal += lc
	}
	tierCut := roundBig(subtotal*tierBP, 10000)
	net := subtotal - tierCut
	couponCut := int64(0)
	if strings.HasPrefix(coupon, "PCT") {
		n, _ := strconv.ParseInt(coupon[3:], 10, 64)
		couponCut = roundBig(net*n, 100)
	} else if strings.HasPrefix(coupon, "FIXED") {
		n, _ := strconv.ParseInt(coupon[5:], 10, 64)
		couponCut = n * 100
		if couponCut > net {
			couponCut = net
		}
	}
	net -= couponCut
	if coupon != "FREESHIP" && net < threshold {
	} else {
		ship = 0
	}
	tax := roundBig(net*taxBP, 10000)
	applied := []string{}
	if tierCut > 0 {
		applied = append(applied, "tier")
	}
	if couponCut > 0 {
		applied = append(applied, "coupon")
	}
	if ship == 0 {
		applied = append(applied, "free-shipping")
	}
	if tax > 0 {
		applied = append(applied, "tax")
	}
	return expected(lines, subtotal, tierCut, couponCut, ship, tax, net+ship+tax, applied...)
}
func check(t *testing.T, g Request, want Outcome) {
	t.Helper()
	got := Solution(g)
	if !equal(got, want) {
		t.Fatalf("Solution(%+v) = %+v, want %+v", g, got, want)
	}
}
func equal(a, b Outcome) bool {
	if (a.Err == nil) != (b.Err == nil) || (a.Quote == nil) != (b.Quote == nil) {
		return false
	}
	if a.Err != nil {
		return a.Err.Code == b.Err.Code && sameIndex(a.Err.Index, b.Err.Index)
	}
	x, y := a.Quote, b.Quote
	if x.Subtotal != y.Subtotal || x.TierDiscount != y.TierDiscount ||
		x.CouponDiscount != y.CouponDiscount || x.Shipping != y.Shipping ||
		x.Tax != y.Tax || x.Total != y.Total || len(x.Lines) != len(y.Lines) ||
		strings.Join(x.Applied, "\x00") != strings.Join(y.Applied, "\x00") {
		return false
	}
	for i := range x.Lines {
		if x.Lines[i] != y.Lines[i] {
			return false
		}
	}
	return true
}
func sameIndex(a, b *int) bool {
	if a == nil || b == nil {
		return a == nil && b == nil
	}
	return *a == *b
}

func TestOrderQuoteWorkedExamples(t *testing.T) {
	cases := []struct {
		g Request
		w Outcome
	}{
		{
			request([]RawItem{item(" ab-12 ", 2, "10.00"), item("CD-34", 1, "5.50")}, "Silver", "", "us"),
			expected([]Line{{"AB-12", 2, 1000, 2000}, {"CD-34", 1, 550, 550}},
				2550, 128, 0, 500, 170, 3092, "tier", "tax"),
		},
		{
			request([]RawItem{item("X1X", 10, "20.00")}, "gold", "pct10", "EU"),
			expected([]Line{{"X1X", 10, 2000, 20000}},
				20000, 2000, 1800, 0, 3240, 19440, "tier", "coupon", "free-shipping", "tax"),
		},
		{
			request([]RawItem{item("aaa", 3, "1.00"), item("AAA", 4, "1")}, "basic", "FIXED5", "ASIA"),
			expected([]Line{{"AAA", 7, 100, 700}},
				700, 0, 500, 1200, 20, 1420, "coupon", "tax"),
		},
		{
			request([]RawItem{item("ZZZ", 1, "0.01")}, "silver", " freeship ", "EU"),
			expected([]Line{{"ZZZ", 1, 1, 1}}, 1, 0, 0, 0, 0, 1, "free-shipping"),
		},
		{
			request([]RawItem{item("RND", 1, "2.50")}, "basic", "", "US"),
			expected([]Line{{"RND", 1, 250, 250}}, 250, 0, 0, 500, 18, 768, "tax"),
		},
		{
			request([]RawItem{item("CAP", 1, "3.00")}, "basic", "FIXED500", "US"),
			expected([]Line{{"CAP", 1, 300, 300}}, 300, 0, 300, 500, 0, 500, "coupon"),
		},
	}
	for _, c := range cases {
		check(t, c.g, c.w)
		check(t, c.g, oracle(c.g))
	}
}
func TestOrderQuoteErrorsAndBoundaries(t *testing.T) {
	cases := []struct {
		g    Request
		code string
		idx  *int
	}{
		{request(nil, "basic", "", "EU"), "EMPTY_ORDER", nil},
		{request([]RawItem{item("a", 1, "1")}, "basic", "", "EU"), "BAD_SKU", at(0)},
		{request([]RawItem{item("ABC", 0, "1")}, "basic", "", "EU"), "BAD_QTY", at(0)},
		{request([]RawItem{item("ABC", -1, "1")}, "basic", "", "EU"), "BAD_QTY", at(0)},
		{request([]RawItem{item("ABC", 1, "1.234")}, "basic", "", "EU"), "BAD_PRICE", at(0)},
		{
			request([]RawItem{item("ABC", 1, "1"), item("abc", 1, "2")}, "basic", "", "EU"),
			"PRICE_CONFLICT", at(1),
		},
		{
			request([]RawItem{item("ABC", 600, "1"), item("abc", 500, "1.0")}, "basic", "", "EU"),
			"BAD_QTY", at(1),
		},
		{request([]RawItem{item("ABC", 1, "1")}, "platinum", "PCT0", "MARS"), "BAD_TIER", nil},
		{request([]RawItem{item("ABC", 1, "1")}, "basic", "PCT0", "MARS"), "BAD_COUPON", nil},
		{request([]RawItem{item("ABC", 1, "1")}, "basic", "", "MARS"), "BAD_REGION", nil},
	}
	for _, c := range cases {
		check(t, c.g, fail(c.code, c.idx))
		check(t, c.g, oracle(c.g))
	}
	precedence := []Request{
		request(make([]RawItem, 51), "bad", "", "EU"),
		request(
			[]RawItem{item("ABC", 1, "1"), item("BAD", 0, "bad"), item("BAD", 1, "1")},
			"basic", "", "EU",
		),
		request(
			[]RawItem{item("ABC", 1, "1"), item("abc", 1, "2"), item("bad", 0, "1")},
			"basic", "", "EU",
		),
		request([]RawItem{item("ABC", 1, "1"), item("abc", 0, "2")}, "basic", "", "EU"),
		request([]RawItem{item("ABC", 1, "1"), item("abc", 1, "2")}, "bad", "PCT0", "MARS"),
	}
	wants := []Outcome{
		fail("TOO_MANY_ITEMS", nil),
		fail("BAD_QTY", at(1)),
		fail("BAD_QTY", at(2)),
		fail("BAD_QTY", at(1)),
		fail("PRICE_CONFLICT", at(1)),
	}
	for i, given := range precedence {
		check(t, given, wants[i])
		check(t, given, oracle(given))
	}
	for _, merged := range []struct {
		quantities [2]int64
		code       string
	}{
		{[2]int64{500, 500}, ""},
		{[2]int64{999, 1}, ""},
		{[2]int64{500, 501}, "BAD_QTY"},
		{[2]int64{1000, 1}, "BAD_QTY"},
	} {
		given := request(
			[]RawItem{item("ABC", merged.quantities[0], "1"), item("abc", merged.quantities[1], "1.00")},
			"basic", "", "EU",
		)
		want := oracle(given)
		if merged.code != "" {
			want = fail(merged.code, at(1))
		}
		check(t, given, want)
		check(t, given, oracle(given))
	}
	for _, coupon := range []string{"PCTX", "FIXED1A", "PCT-5", "PCT5.0", "FIXED 5"} {
		given := request([]RawItem{item("ABC", 1, "1")}, "basic", coupon, "EU")
		check(t, given, fail("BAD_COUPON", nil))
	}
	for _, s := range []string{"AB", "ABCDEFGHIJKLM", "AB_", "AB ", "ÄBC"} {
		g := request([]RawItem{item(s, 1, "1")}, "basic", "", "EU")
		check(t, g, oracle(g))
	}
	for _, p := range []string{
		"0", "0.00", "1.234", "abc", "", "1234567", "1000000", ".50", ".5",
		"1.", "+1", "-1", " 1", "1 ", "1 0", "1,5", "1a", "1e3",
	} {
		g := request([]RawItem{item("ABC", 1, p)}, "basic", "", "EU")
		check(t, g, oracle(g))
	}
	for _, c := range []string{
		"PCT0", "PCT51", "PCT07", "FIXED0", "FIXED501", "FIXED05",
		"PCTX", "FIXED1A", "PCT-5", "PCT5.0", "FIXED 5",
	} {
		g := request([]RawItem{item("ABC", 1, "1")}, "basic", c, "EU")
		check(t, g, oracle(g))
	}
}

type corpusGenerator struct {
	rng  *splitMix64
	next int
}

func (g *corpusGenerator) below(limit int) int {
	return int((g.rng.next() >> 16) % uint64(limit))
}
func (g *corpusGenerator) pick(values []string) string { return values[g.below(len(values))] }
func (g *corpusGenerator) decorate(text string) string {
	if g.below(3) == 0 {
		text = strings.ToLower(text)
	}
	if g.below(4) == 0 {
		text = " " + text + " "
	}
	return text
}
func (g *corpusGenerator) tier() string {
	text := g.pick([]string{"basic", "silver", "gold"})
	if g.below(2) == 0 {
		text = strings.ToUpper(text)
	}
	return g.decorate(text)
}
func (g *corpusGenerator) region() string {
	return g.decorate(g.pick([]string{"EU", "US", "ASIA"}))
}
func (g *corpusGenerator) coupon() string {
	text := ""
	switch g.below(4) {
	case 1:
		text = "PCT" + strconv.Itoa(1+g.below(50))
	case 2:
		text = "FIXED" + strconv.Itoa(1+g.below(500))
	case 3:
		text = "FREESHIP"
	}
	return g.decorate(text)
}
func (g *corpusGenerator) sku() string {
	g.next++
	alphabet := "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-"
	letters, tail := 1+g.below(6), "-"+strconv.Itoa(g.next)
	if g.below(6) == 0 {
		letters, tail = 12, ""
	}
	var text strings.Builder
	for i := 0; i < letters; i++ {
		letter := alphabet[g.below(len(alphabet))]
		if letter >= 'A' && letter <= 'Z' && g.below(4) == 0 {
			letter += 'a' - 'A'
		}
		text.WriteByte(letter)
	}
	sku := text.String() + tail
	if g.below(3) == 0 {
		sku = " " + sku + " "
	}
	return sku
}
func (g *corpusGenerator) price() string {
	width := 1 + g.below(27)
	cents := int64(1 + g.rng.next()&((uint64(1)<<width)-1))
	if cents > 99999999 {
		cents = 99999999
	}
	return priceText(cents)
}

// probes are random fixtures that land on rounding or boundary values the
// plain random requests would rarely hit; four of five requests stay random.
func (g *corpusGenerator) valid() Request {
	tier, coupon, region := g.tier(), g.coupon(), g.region()
	if g.below(4) != 0 {
		return g.randomRows(tier, coupon, region)
	}
	switch g.below(7) {
	case 0, 6:
		return g.mergedRows(tier, coupon, region)
	case 1:
		return g.aroundThreshold()
	case 2:
		return g.cappedRows(tier, region)
	case 3, 5:
		return g.roundedRows()
	case 4:
		return g.fiftyRows(tier, coupon, region)
	}
	return g.randomRows(tier, coupon, region)
}
func (g *corpusGenerator) randomRows(tier, coupon, region string) Request {
	rows := make([]RawItem, 1+g.below(5))
	for i := range rows {
		rows[i] = item(g.sku(), int64(1+g.below(1000)), g.price())
	}
	return request(rows, tier, coupon, region)
}
func (g *corpusGenerator) fiftyRows(tier, coupon, region string) Request {
	rows := make([]RawItem, 50)
	for i := range rows {
		rows[i] = item(g.sku(), int64(1+g.below(1000)), g.price())
	}
	return request(rows, tier, coupon, region)
}
func (g *corpusGenerator) mergedRows(tier, coupon, region string) Request {
	first := int64(1 + g.below(999))
	sku, price := g.sku(), g.price()
	rows := []RawItem{item(sku, first, price), item(sku, 1000-first, price)}
	return request(rows, tier, coupon, region)
}
func (g *corpusGenerator) aroundThreshold() Request {
	regions := []string{"EU", "US", "ASIA"}
	thresholds := []int64{10000, 7500, 15000}
	index := g.below(len(regions))
	row := item(g.sku(), 1, priceText(thresholds[index]))
	return request([]RawItem{row}, "basic", "", g.decorate(regions[index]))
}
func (g *corpusGenerator) cappedRows(tier, region string) Request {
	limit := 1 + g.below(500)
	cents := int64(1 + g.below(limit*100-1))
	coupon := "FIXED" + strconv.Itoa(limit)
	return request([]RawItem{item(g.sku(), 1, priceText(cents))}, tier, coupon, region)
}
func (g *corpusGenerator) roundedRows() Request {
	switch g.below(3) {
	case 0:
		subtotal, tier := int64(10+20*g.below(4999999)), "silver"
		if g.below(2) == 0 {
			subtotal, tier = int64(5+10*g.below(9999999)), "gold"
		}
		return request([]RawItem{item(g.sku(), 1, priceText(subtotal))}, tier, "", g.region())
	case 1:
		if g.below(2) == 0 {
			subtotal := int64(50 + 100*g.below(999999))
			return request([]RawItem{item(g.sku(), 1, priceText(subtotal))}, "basic", "", "US")
		}
		subtotal := int64(5 + 10*g.below(9999999))
		return request([]RawItem{item(g.sku(), 1, priceText(subtotal))}, "basic", "", "ASIA")
	default:
		ratios := []int{1, 3, 5, 7, 9, 11, 13, 17, 19, 21, 23, 25, 27, 29, 31, 33, 35, 37, 39, 41, 43, 45, 47, 49}
		coupon := "PCT" + strconv.Itoa(ratios[g.below(len(ratios))])
		subtotal := int64(50 + 100*g.below(999999))
		return request([]RawItem{item(g.sku(), 1, priceText(subtotal))}, "basic", coupon, g.region())
	}
}
func (g *corpusGenerator) invalid() Request {
	tier, coupon, region := g.tier(), g.coupon(), g.region()
	switch g.below(10) {
	case 0:
		return request(nil, tier, coupon, region)
	case 1:
		rows := make([]RawItem, 51)
		for i := range rows {
			rows[i] = item(g.sku(), int64(1+g.below(1000)), g.price())
		}
		return request(rows, tier, coupon, region)
	case 2:
		bad := []string{"AB", "ABCDEFGHIJKLM", "AB_", "AB CD"}
		return request([]RawItem{item(g.pick(bad), 1, "1")}, tier, coupon, region)
	case 3:
		quantities := []int64{0, -1, 1001}
		return request([]RawItem{item(g.sku(), quantities[g.below(len(quantities))], "1")}, tier, coupon, region)
	case 4:
		prices := []string{"0", "1.234", "1000000", "1."}
		return request([]RawItem{item(g.sku(), 1, g.pick(prices))}, tier, coupon, region)
	case 5:
		sku := g.sku()
		rows := []RawItem{item(sku, 1, "1"), item(sku, 1, "2")}
		return request(rows, tier, coupon, region)
	case 6:
		return request([]RawItem{item(g.sku(), 1, "1")}, "platinum", coupon, region)
	case 7:
		bad := []string{"PCT51", "FIXED501", "PCT07", "PCT0", "FIXED0"}
		return request([]RawItem{item(g.sku(), 1, "1")}, tier, g.pick(bad), region)
	case 8:
		return request([]RawItem{item(g.sku(), 1, "1")}, tier, coupon, "MARS")
	default:
		sku := g.sku()
		first := int64(1 + g.below(1000))
		rows := []RawItem{item(sku, first, "1"), item(sku, 1001-first, "1")}
		return request(rows, tier, coupon, region)
	}
}
func couponKind(coupon string) string {
	text := strings.ToUpper(strings.TrimSpace(coupon))
	switch {
	case text == "":
		return "empty"
	case strings.HasPrefix(text, "PCT"):
		return "PCT"
	case strings.HasPrefix(text, "FIXED"):
		return "FIXED"
	case text == "FREESHIP":
		return "FREESHIP"
	}
	return text
}
func TestOrderQuoteSeededRandomAndDiversity(t *testing.T) {
	const total = 4000
	generator := &corpusGenerator{rng: &splitMix64{state: 20261017}}
	tiers := []string{"basic", "silver", "gold"}
	coupons := []string{"empty", "PCT", "FIXED", "FREESHIP"}
	regions := []string{"EU", "US", "ASIA"}
	validTiers, validRegions, validCoupons := map[string]bool{}, map[string]bool{}, map[string]bool{}
	errorCodes := map[string]bool{}
	valid, invalid := 0, 0
	for n := 0; n < total; n++ {
		given := generator.valid()
		if generator.below(8) == 0 {
			given = generator.invalid()
		}
		want := oracle(given)
		if want.Err == nil {
			valid++
			validTiers[strings.ToLower(strings.TrimSpace(given.Tier))] = true
			validRegions[strings.ToUpper(strings.TrimSpace(given.Region))] = true
			validCoupons[couponKind(given.Coupon)] = true
		} else {
			invalid++
			errorCodes[want.Err.Code] = true
		}
		check(t, given, want)
	}
	if valid*2 < total {
		t.Fatalf("valid request ratio below 50%%: %d/%d", valid, total)
	}
	if invalid == 0 {
		t.Fatalf("generator produced no invalid requests")
	}
	for _, value := range tiers {
		if !validTiers[value] {
			t.Fatalf("tier not covered: %s", value)
		}
	}
	for _, value := range regions {
		if !validRegions[value] {
			t.Fatalf("region not covered: %s", value)
		}
	}
	for _, value := range coupons {
		if !validCoupons[value] {
			t.Fatalf("coupon kind not covered: %s", value)
		}
	}
	for _, code := range []string{"EMPTY_ORDER", "TOO_MANY_ITEMS", "BAD_SKU", "BAD_QTY", "BAD_PRICE", "PRICE_CONFLICT", "BAD_TIER", "BAD_COUPON", "BAD_REGION"} {
		if !errorCodes[code] {
			t.Fatalf("error code not covered: %s", code)
		}
	}
	t.Logf("seeded distribution: valid=%d invalid=%d tiers=%v regions=%v coupon_kinds=%v errors=%v", valid, invalid, validTiers, validRegions, validCoupons, errorCodes)
}
func TestOrderQuoteReferenceAndMaximum(t *testing.T) {
	for _, edge := range []struct {
		region    string
		threshold int64
	}{{"EU", 10000}, {"US", 7500}, {"ASIA", 15000}} {
		for _, amount := range []int64{edge.threshold - 1, edge.threshold} {
			g := request([]RawItem{item("EDGE", 1, priceText(amount))}, "basic", "", edge.region)
			check(t, g, oracle(g))
		}
		subtotal := edge.threshold * 112 / 100
		g := request([]RawItem{item("EDGE", 1, priceText(subtotal))}, "gold", "PCT10", edge.region)
		want := oracle(g)
		if want.Quote == nil || want.Quote.Subtotal < edge.threshold ||
			want.Quote.Subtotal-want.Quote.TierDiscount < edge.threshold ||
			want.Quote.Subtotal-want.Quote.TierDiscount-want.Quote.CouponDiscount >= edge.threshold ||
			want.Quote.Shipping == 0 {
			t.Fatalf("bad threshold fixture: %+v", want)
		}
		check(t, g, want)
	}
	ordered := request(
		[]RawItem{item("a1x", 1, "1"), item("A1X", 1, "1"), item("A-1", 1, "1"), item("A01", 1, "1")},
		"basic", "", "EU",
	)
	check(t, ordered, oracle(ordered))
	fifty := make([]RawItem, 50)
	for i := range fifty {
		fifty[i] = item("S"+strconv.Itoa(10+i), int64(i+1), "1.25")
	}
	fiftyRequest := request(fifty, "gold", "PCT7", "ASIA")
	check(t, fiftyRequest, oracle(fiftyRequest))
	maxRows := func() []RawItem {
		rows := make([]RawItem, 50)
		for i := range rows {
			rows[i] = item("S"+strconv.Itoa(10+i), 1000, "999999.99")
		}
		return rows
	}
	for _, tier := range []string{"basic", "silver", "gold"} {
		for _, region := range []string{"EU", "US", "ASIA"} {
			g := request(maxRows(), tier, "", region)
			check(t, g, oracle(g))
		}
	}
}
