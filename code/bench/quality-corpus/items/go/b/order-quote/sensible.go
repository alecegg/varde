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
type checkedItem struct {
	sku        string
	qty, cents int64
}
type rates struct{ tax, shipping, threshold int64 }
type options struct{ tier, coupon, region string }
type quoteAmounts struct{ tierCut, couponCut, net, shipping, tax int64 }

var skuRule = regexp.MustCompile(`^[A-Z0-9-]{3,12}$`)
var priceRule = regexp.MustCompile(`^[0-9]{1,6}(\.[0-9]{1,2})?$`)

// Solution quotes an order in integer cents with tier, coupon, shipping, and regional tax.
func Solution(request Request) Outcome {
	rows := normalise(request.Items)
	if err := validate(rows); err != nil {
		return Outcome{Err: err}
	}
	merged, err := mergeItems(rows)
	if err != nil {
		return Outcome{Err: err}
	}
	values := options{request.Tier, request.Coupon, request.Region}
	tier, coupon, region, err := validateOptions(values)
	if err != nil {
		return Outcome{Err: err}
	}
	lines, subtotal := priceLines(merged)
	return finish(lines, subtotal, tier, coupon, region)
}
func normalise(items []RawItem) []RawItem {
	rows := make([]RawItem, len(items))
	for i, row := range items {
		row.Sku = strings.ToUpper(strings.TrimSpace(row.Sku))
		rows[i] = row
	}
	return rows
}
func validate(rows []RawItem) *QuoteError {
	if len(rows) == 0 {
		return &QuoteError{Code: "EMPTY_ORDER"}
	}
	if len(rows) > 50 {
		return &QuoteError{Code: "TOO_MANY_ITEMS"}
	}
	for i, row := range rows {
		if err := validateItem(row, i); err != nil {
			return err
		}
	}
	return nil
}
func validateItem(row RawItem, position int) *QuoteError {
	if !skuRule.MatchString(row.Sku) {
		return &QuoteError{Code: "BAD_SKU", Index: &position}
	}
	if row.Qty < 1 || row.Qty > 1000 {
		return &QuoteError{Code: "BAD_QTY", Index: &position}
	}
	if _, ok := priceCents(row.Price); !ok {
		return &QuoteError{Code: "BAD_PRICE", Index: &position}
	}
	return nil
}
func priceCents(text string) (int64, bool) {
	if !priceRule.MatchString(text) {
		return 0, false
	}
	parts := strings.Split(text, ".")
	whole, _ := strconv.ParseInt(parts[0], 10, 64)
	fraction := ""
	if len(parts) == 2 {
		fraction = parts[1]
	}
	fraction += strings.Repeat("0", 2-len(fraction))
	var tail int64
	if fraction != "" {
		tail, _ = strconv.ParseInt(fraction, 10, 64)
	}
	value := whole*100 + tail
	return value, value > 0
}
func mergeItems(items []RawItem) (map[string]checkedItem, *QuoteError) {
	merged := make(map[string]checkedItem, len(items))
	for i, row := range items {
		if err := mergeItem(merged, row, i); err != nil {
			return nil, err
		}
	}
	return merged, nil
}
func mergeItem(merged map[string]checkedItem, row RawItem, position int) *QuoteError {
	cents, _ := priceCents(row.Price)
	old, exists := merged[row.Sku]
	if !exists {
		merged[row.Sku] = checkedItem{row.Sku, row.Qty, cents}
		return nil
	}
	if old.cents != cents {
		return &QuoteError{Code: "PRICE_CONFLICT", Index: &position}
	}
	old.qty += row.Qty
	if old.qty > 1000 {
		return &QuoteError{Code: "BAD_QTY", Index: &position}
	}
	merged[row.Sku] = old
	return nil
}
func normaliseOptions(tier, coupon, region string) options {
	return options{
		tier:   strings.ToLower(strings.TrimSpace(tier)),
		coupon: strings.ToUpper(strings.TrimSpace(coupon)),
		region: strings.ToUpper(strings.TrimSpace(region)),
	}
}
func validateOptions(values options) (string, string, rates, *QuoteError) {
	values = normaliseOptions(values.tier, values.coupon, values.region)
	tier, coupon, region := values.tier, values.coupon, values.region
	if err := validateTier(tier); err != nil {
		return "", "", rates{}, err
	}
	if err := validateCoupon(coupon); err != nil {
		return "", "", rates{}, err
	}
	r, ok := regionRates(region)
	if !ok {
		return "", "", rates{}, &QuoteError{Code: "BAD_REGION"}
	}
	return tier, coupon, r, nil
}
func validateTier(tier string) *QuoteError {
	if tier == "basic" || tier == "silver" || tier == "gold" {
		return nil
	}
	return &QuoteError{Code: "BAD_TIER"}
}
func validateCoupon(coupon string) *QuoteError {
	if coupon == "" || validCoupon(coupon) {
		return nil
	}
	return &QuoteError{Code: "BAD_COUPON"}
}
func validCoupon(c string) bool {
	if c == "FREESHIP" {
		return true
	}
	for _, prefix := range []string{"PCT", "FIXED"} {
		if strings.HasPrefix(c, prefix) {
			suffix := strings.TrimPrefix(c, prefix)
			n, e := strconv.Atoi(suffix)
			limit := 50
			if prefix == "FIXED" {
				limit = 500
			}
			return e == nil && n >= 1 && n <= limit && strconv.Itoa(n) == suffix
		}
	}
	return false
}
func regionRates(region string) (rates, bool) {
	switch region {
	case "EU":
		return rates{2000, 800, 10000}, true
	case "US":
		return rates{700, 500, 7500}, true
	case "ASIA":
		return rates{1000, 1200, 15000}, true
	}
	return rates{}, false
}
func priceLines(items map[string]checkedItem) ([]Line, int64) {
	keys := make([]string, 0, len(items))
	for key := range items {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	lines := make([]Line, 0, len(keys))
	var subtotal int64
	for _, key := range keys {
		row := items[key]
		amount := row.qty * row.cents
		lines = append(lines, Line{row.sku, row.qty, row.cents, amount})
		subtotal += amount
	}
	return lines, subtotal
}
func tierDiscount(subtotal int64, tier string) int64 {
	rate := int64(0)
	if tier == "silver" {
		rate = 500
	}
	if tier == "gold" {
		rate = 1000
	}
	numerator := subtotal * rate
	whole := numerator / 10000
	if numerator%10000*2 >= 10000 {
		whole++
	}
	return whole
}
func couponDiscount(net int64, coupon string) int64 {
	if strings.HasPrefix(coupon, "PCT") {
		n, _ := strconv.ParseInt(coupon[3:], 10, 64)
		numerator := net * n
		whole := numerator / 100
		if numerator%100*2 >= 100 {
			whole++
		}
		return whole
	}
	if strings.HasPrefix(coupon, "FIXED") {
		n, _ := strconv.ParseInt(coupon[5:], 10, 64)
		value := n * 100
		if value > net {
			return net
		}
		return value
	}
	return 0
}
func finish(lines []Line, subtotal int64, tier, coupon string, region rates) Outcome {
	amounts := calculateAdjustments(subtotal, tier, coupon, region)
	applied := appliedRules(amounts)
	total := amounts.net + amounts.shipping + amounts.tax
	quote := &Quote{
		Lines: lines, Subtotal: subtotal, TierDiscount: amounts.tierCut,
		CouponDiscount: amounts.couponCut, Shipping: amounts.shipping,
		Tax: amounts.tax, Total: total, Applied: applied,
	}
	return Outcome{Quote: quote}
}
func appliedRules(amounts quoteAmounts) []string {
	applied := make([]string, 0, 4)
	if amounts.tierCut > 0 {
		applied = append(applied, "tier")
	}
	if amounts.couponCut > 0 {
		applied = append(applied, "coupon")
	}
	if amounts.shipping == 0 {
		applied = append(applied, "free-shipping")
	}
	if amounts.tax > 0 {
		applied = append(applied, "tax")
	}
	return applied
}
func calculateAdjustments(subtotal int64, tier, coupon string, region rates) quoteAmounts {
	tierCut := tierDiscount(subtotal, tier)
	afterTier := subtotal - tierCut
	couponCut := couponDiscount(afterTier, coupon)
	net := afterTier - couponCut
	shipping := region.shipping
	if coupon == "FREESHIP" || net >= region.threshold {
		shipping = 0
	}
	numerator := net * region.tax
	tax := numerator / 10000
	if numerator%10000*2 >= 10000 {
		tax++
	}
	return quoteAmounts{tierCut, couponCut, net, shipping, tax}
}
