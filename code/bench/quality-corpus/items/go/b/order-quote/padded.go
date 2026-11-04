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
type adjustment struct{ subtotal, tierCut, couponCut, net, shipping, tax int64 }

var skuRule = regexp.MustCompile(`^[A-Z0-9-]{3,12}$`)
var priceRule = regexp.MustCompile(`^[0-9]{1,6}(\.[0-9]{1,2})?$`)

// Solution quotes an order in integer cents with tier, coupon, shipping, and regional tax.
func Solution(request Request) Outcome {
	rows := normalise(request.Items)
	checked, err := validate(rows)
	if err != nil {
		return Outcome{Err: err}
	}
	merged, err := mergeItems(checked)
	if err != nil {
		return Outcome{Err: err}
	}
	tier, coupon, region, err := validateOptions(request.Tier, request.Coupon, request.Region)
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
func validate(rows []RawItem) ([]checkedItem, *QuoteError) {
	if problem := checkItemCount(rows); problem != nil {
		return nil, problem
	}
	checked := make([]checkedItem, 0, len(rows))
	for position, row := range rows {
		checkedRow, problem := validateItem(row, position)
		if problem != nil {
			return nil, problem
		}
		checked = append(checked, checkedRow)
	}
	return checked, nil
}
func validateItem(row RawItem, position int) (checkedItem, *QuoteError) {
	if issue := validateSKU(row.Sku, position); issue != nil {
		return checkedItem{}, issue
	}
	if issue := validateQuantity(row.Qty, position); issue != nil {
		return checkedItem{}, issue
	}
	cents, valid := priceCents(row.Price)
	if !valid {
		return checkedItem{}, &QuoteError{Code: "BAD_PRICE", Index: &position}
	}
	return checkedItem{row.Sku, row.Qty, cents}, nil
}
func validateSKU(sku string, position int) *QuoteError {
	if len(sku) < 3 || len(sku) > 12 || !skuRule.MatchString(sku) {
		return &QuoteError{Code: "BAD_SKU", Index: &position}
	}
	return nil
}
func validateQuantity(quantity int64, position int) *QuoteError {
	withinBounds := quantity >= 1 && quantity <= 1000
	if !withinBounds {
		return &QuoteError{Code: "BAD_QTY", Index: &position}
	}
	return nil
}
func checkItemCount(rows []RawItem) *QuoteError {
	itemCount := len(rows)
	if itemCount == 0 {
		return &QuoteError{Code: "EMPTY_ORDER"}
	}
	if itemCount > 50 {
		return &QuoteError{Code: "TOO_MANY_ITEMS"}
	}
	return nil
}
func priceCents(text string) (int64, bool) {
	if !priceRule.MatchString(text) {
		return 0, false
	}
	parts := strings.Split(text, ".")
	whole, _ := strconv.ParseInt(parts[0], 10, 64)
	fractionText := ""
	if len(parts) == 2 {
		fractionText = parts[1]
	}
	fractionText += strings.Repeat("0", 2-len(fractionText))
	fraction, _ := strconv.ParseInt(fractionText, 10, 64)
	totalCents := whole*100 + fraction
	return totalCents, totalCents > 0
}
func mergeItems(items []checkedItem) (map[string]checkedItem, *QuoteError) {
	merged := make(map[string]checkedItem, len(items))
	for position, row := range items {
		if problem := mergeItem(merged, row, position); problem != nil {
			return nil, problem
		}
	}
	return merged, nil
}
func mergeItem(merged map[string]checkedItem, row checkedItem, position int) *QuoteError {
	old, exists := merged[row.sku]
	if !exists {
		merged[row.sku] = row
		return nil
	}
	if old.cents != row.cents {
		return &QuoteError{Code: "PRICE_CONFLICT", Index: &position}
	}
	old.qty += row.qty
	if old.qty > 1000 {
		return &QuoteError{Code: "BAD_QTY", Index: &position}
	}
	merged[row.sku] = old
	return nil
}
func normalizeOptions(tier, coupon, region string) (string, string, string, *QuoteError) {
	normalizedTier := strings.ToLower(strings.TrimSpace(tier))
	normalizedCoupon := strings.ToUpper(strings.TrimSpace(coupon))
	normalizedRegion := strings.ToUpper(strings.TrimSpace(region))
	if !validTier(normalizedTier) {
		return "", "", "", &QuoteError{Code: "BAD_TIER"}
	}
	return normalizedTier, normalizedCoupon, normalizedRegion, nil
}
func validateOptions(tier, coupon, region string) (string, string, rates, *QuoteError) {
	var problem *QuoteError
	tier, coupon, region, problem = normalizeOptions(tier, coupon, region)
	if problem != nil {
		return "", "", rates{}, problem
	}
	if !validCoupon(coupon) {
		return "", "", rates{}, &QuoteError{Code: "BAD_COUPON"}
	}
	regionInfo, problem := regionRates(region)
	if problem != nil {
		return "", "", rates{}, problem
	}
	return tier, coupon, regionInfo, nil
}
func validTier(tier string) bool {
	return tier == "basic" || tier == "silver" || tier == "gold"
}
func validCoupon(c string) bool {
	if c == "FREESHIP" {
		return true
	}
	valid := c == ""
	for _, prefix := range []string{"PCT", "FIXED"} {
		if strings.HasPrefix(c, prefix) {
			suffix := strings.TrimPrefix(c, prefix)
			n, err := strconv.Atoi(suffix)
			limit := 50
			if prefix == "FIXED" {
				limit = 500
			}
			valid = err == nil && n >= 1 && n <= limit && strconv.Itoa(n) == suffix
		}
	}
	return valid
}

func regionRates(region string) (rates, *QuoteError) {
	switch region {
	case "EU":
		return rates{2000, 800, 10000}, nil
	case "US":
		return rates{700, 500, 7500}, nil
	case "ASIA":
		return rates{1000, 1200, 15000}, nil
	}
	return rates{}, &QuoteError{Code: "BAD_REGION"}
}
func priceLines(items map[string]checkedItem) ([]Line, int64) {
	var keys []string
	for key := range items {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	var lines []Line
	var subtotal int64
	for _, key := range keys {
		row := items[key]
		amount := row.qty * row.cents
		lines = append(lines, Line{row.sku, row.qty, row.cents, amount})
		subtotal += amount
	}
	return lines, subtotal
}
func roundHalfUp(value, rate, base int64) int64 {
	numerator := value*rate*2 + base
	return numerator / (2 * base)
}
func tierDiscount(subtotal int64, tier string) int64 {
	rate := int64(0)
	if tier == "silver" {
		rate = 500
	}
	if tier == "gold" {
		rate = 1000
	}
	return roundHalfUp(subtotal, rate, 10000)
}
func couponDiscount(net int64, coupon string) int64 {
	if strings.HasPrefix(coupon, "PCT") {
		n, _ := strconv.ParseInt(coupon[3:], 10, 64)
		return roundHalfUp(net, n, 100)
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
	tierCut := tierDiscount(subtotal, tier)
	afterTier := subtotal - tierCut
	couponCut := couponDiscount(afterTier, coupon)
	net := afterTier - couponCut
	shipping := region.shipping
	if coupon == "FREESHIP" || net >= region.threshold {
		shipping = 0
	}
	tax := roundHalfUp(net, region.tax, 10000)
	money := adjustment{subtotal, tierCut, couponCut, net, shipping, tax}
	return Outcome{Quote: assembledQuote(lines, money)}
}
func appliedAdjustments(money adjustment) []string {
	labels := []struct {
		name string
		used bool
	}{
		{"tier", money.tierCut > 0},
		{"coupon", money.couponCut > 0},
		{"free-shipping", money.shipping == 0},
		{"tax", money.tax > 0},
	}
	applied := make([]string, 0, len(labels))
	for _, label := range labels {
		if label.used {
			applied = append(applied, label.name)
		}
	}
	return applied
}
func assembledQuote(lines []Line, money adjustment) *Quote {
	return &Quote{
		Lines: lines, Subtotal: money.subtotal, TierDiscount: money.tierCut,
		CouponDiscount: money.couponCut, Shipping: money.shipping, Tax: money.tax,
		Total:   money.net + money.shipping + money.tax,
		Applied: appliedAdjustments(money),
	}
}
