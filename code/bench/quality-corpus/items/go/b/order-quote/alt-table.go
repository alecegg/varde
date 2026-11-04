package corpus

import (
	"regexp"
	"sort"
	"strconv"
	"strings"
)

type Request struct {
	Items                []RawItem
	Tier, Coupon, Region string
}
type RawItem struct {
	Sku   string
	Qty   int64
	Price string
}
type Line struct {
	Sku                       string
	Qty, UnitCents, LineCents int64
}
type Quote struct {
	Lines                                                        []Line
	Subtotal, TierDiscount, CouponDiscount, Shipping, Tax, Total int64
	Applied                                                      []string
}
type QuoteError struct {
	Code  string
	Index *int
}
type Outcome struct {
	Quote *Quote
	Err   *QuoteError
}

type tableItem struct {
	sku        string
	qty, cents int64
}
type quotePlan struct {
	tier, coupon string
	region       rateCard
}
type rateCard struct {
	code                     string
	tax, shipping, threshold int64
}
type percentage struct {
	key         string
	basisPoints int64
}
type couponOffer struct {
	prefix, mode string
	maximum      uint64
}

var tableSKU = regexp.MustCompile(`^[A-Z0-9-]{3,12}$`)
var tierRates = []percentage{{"basic", 0}, {"silver", 500}, {"gold", 1000}}
var couponOffers = []couponOffer{{"PCT", "percent", 50}, {"FIXED", "fixed", 500}}
var regionCards = []rateCard{
	{"EU", 2000, 800, 10000},
	{"US", 700, 500, 7500},
	{"ASIA", 1000, 1200, 15000},
}
var labelRules = []struct {
	text   string
	onZero bool
}{{"tier", false}, {"coupon", false}, {"free-shipping", true}, {"tax", false}}

// Solution interprets validation and pricing tables to quote normalized order lines.
func Solution(request Request) Outcome {
	if len(request.Items) == 0 {
		return Outcome{Err: &QuoteError{Code: "EMPTY_ORDER"}}
	}
	if len(request.Items) > 50 {
		return Outcome{Err: &QuoteError{Code: "TOO_MANY_ITEMS"}}
	}
	items, issue := readRows(request.Items)
	if issue != nil {
		return Outcome{Err: issue}
	}
	grouped, issue := combineRows(items)
	if issue != nil {
		return Outcome{Err: issue}
	}
	plan, issue := readPlan(request)
	if issue != nil {
		return Outcome{Err: issue}
	}
	return Outcome{Quote: interpretQuote(grouped, plan)}
}

func readRows(rows []RawItem) ([]tableItem, *QuoteError) {
	var values []tableItem
	for i, row := range rows {
		sku := strings.ToUpper(strings.TrimSpace(row.Sku))
		cents, priceOK := parseTablePrice(row.Price)
		code := ""
		switch {
		case !tableSKU.MatchString(sku):
			code = "BAD_SKU"
		case row.Qty < 1 || row.Qty > 1000:
			code = "BAD_QTY"
		case !priceOK:
			code = "BAD_PRICE"
		}
		if code != "" {
			return nil, &QuoteError{Code: code, Index: &i}
		}
		values = append(values, tableItem{sku, row.Qty, cents})
	}
	return values, nil
}

func parseTablePrice(text string) (int64, bool) {
	wholeText, fracText, hasDot := strings.Cut(text, ".")
	whole, wholeOK := accumulateDigits(wholeText, 1, 6)
	fracLen := len(fracText)
	frac, fracOK := accumulateDigits(fracText, 1, 2)
	if !hasDot {
		frac, fracOK, fracLen = 0, true, 2
	}
	if fracLen == 1 {
		frac *= 10
	}
	cents := whole*100 + frac
	return cents, wholeOK && fracOK && cents > 0
}

func accumulateDigits(text string, least, most int) (int64, bool) {
	var total int64
	for i := 0; i < len(text); i++ {
		if text[i] < '0' || text[i] > '9' {
			return 0, false
		}
		total = total*10 + int64(text[i]-'0')
	}
	return total, len(text) >= least && len(text) <= most
}

func combineRows(rows []tableItem) (map[string]tableItem, *QuoteError) {
	merged := make(map[string]tableItem, len(rows))
	for i, row := range rows {
		prior, found := merged[row.sku]
		if found && prior.cents != row.cents {
			return nil, &QuoteError{Code: "PRICE_CONFLICT", Index: &i}
		}
		if found && prior.qty+row.qty > 1000 {
			return nil, &QuoteError{Code: "BAD_QTY", Index: &i}
		}
		row.qty += prior.qty
		merged[row.sku] = row
	}
	return merged, nil
}

func readPlan(request Request) (quotePlan, *QuoteError) {
	plan := quotePlan{
		tier:   strings.ToLower(strings.TrimSpace(request.Tier)),
		coupon: strings.ToUpper(strings.TrimSpace(request.Coupon)),
	}
	if _, ok := tierFor(plan.tier); !ok {
		return quotePlan{}, &QuoteError{Code: "BAD_TIER"}
	}
	if !couponAccepted(plan.coupon) {
		return quotePlan{}, &QuoteError{Code: "BAD_COUPON"}
	}
	regionCode := strings.ToUpper(strings.TrimSpace(request.Region))
	var found bool
	plan.region, found = regionFor(regionCode)
	if !found {
		return quotePlan{}, &QuoteError{Code: "BAD_REGION"}
	}
	return plan, nil
}

func tierFor(code string) (int64, bool) {
	for _, rate := range tierRates {
		if rate.key == code {
			return rate.basisPoints, true
		}
	}
	return 0, false
}

func regionFor(code string) (rateCard, bool) {
	for _, region := range regionCards {
		if region.code == code {
			return region, true
		}
	}
	return rateCard{}, false
}

func couponAccepted(value string) bool {
	if value == "" || value == "FREESHIP" {
		return true
	}
	_, _, valid := matchCoupon(value)
	return valid
}

func matchCoupon(coupon string) (string, int64, bool) {
	for _, kind := range couponOffers {
		digits, found := strings.CutPrefix(coupon, kind.prefix)
		if !found {
			continue
		}
		n, err := strconv.ParseUint(digits, 10, 16)
		plain := err == nil && strconv.FormatUint(n, 10) == digits
		return kind.mode, int64(n), plain && n >= 1 && n <= kind.maximum
	}
	return "", 0, false
}

func interpretQuote(grouped map[string]tableItem, plan quotePlan) *Quote {
	lines := tableLines(grouped)
	var subtotal int64
	for _, line := range lines {
		subtotal += line.LineCents
	}
	tierRate, _ := tierFor(plan.tier)
	tier := roundedBy(subtotal*tierRate, 10000)
	coupon := couponDiscount(subtotal-tier, plan.coupon)
	net := subtotal - tier - coupon
	shipping, tax := shippingAndTax(net, plan)
	return buildTableQuote(lines, subtotal, [5]int64{tier, coupon, net, shipping, tax})
}

func tableLines(grouped map[string]tableItem) []Line {
	keys := make([]string, 0, len(grouped))
	for key := range grouped {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	lines := make([]Line, len(keys))
	for i, key := range keys {
		item := grouped[key]
		lines[i] = Line{key, item.qty, item.cents, item.qty * item.cents}
	}
	return lines
}

func shippingAndTax(net int64, plan quotePlan) (int64, int64) {
	shipping := plan.region.shipping
	if plan.coupon == "FREESHIP" || net >= plan.region.threshold {
		shipping = 0
	}
	return shipping, roundedBy(net*plan.region.tax, 10000)
}

func couponDiscount(amount int64, coupon string) int64 {
	mode, n, found := matchCoupon(coupon)
	switch {
	case !found:
		return 0
	case mode == "percent":
		return roundedBy(amount*n, 100)
	case n*100 > amount:
		return amount
	}
	return n * 100
}

func roundedBy(numerator, denominator int64) int64 {
	whole, remainder := numerator/denominator, numerator%denominator
	if remainder*2 >= denominator {
		whole++
	}
	return whole
}

func buildTableQuote(lines []Line, subtotal int64, amounts [5]int64) *Quote {
	tier, coupon, net := amounts[0], amounts[1], amounts[2]
	shipping, tax := amounts[3], amounts[4]
	return &Quote{
		Lines: lines, Subtotal: subtotal, TierDiscount: tier, CouponDiscount: coupon,
		Shipping: shipping, Tax: tax, Total: net + shipping + tax,
		Applied: tableLabels([4]int64{tier, coupon, shipping, tax}),
	}
}

func tableLabels(amounts [4]int64) []string {
	result := make([]string, 0, len(labelRules))
	for i, rule := range labelRules {
		if (amounts[i] == 0) == rule.onZero {
			result = append(result, rule.text)
		}
	}
	return result
}
