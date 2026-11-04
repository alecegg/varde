package corpus

import (
	"regexp"
	"slices"
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

var skuRule = regexp.MustCompile(`^[A-Z0-9-]{3,12}$`)
var priceRule = regexp.MustCompile(`^[0-9]{1,6}(\.[0-9]{1,2})?$`)

// Solution quotes an order in integer cents with tier, coupon, shipping, and regional tax.
func Solution(request Request) Outcome {
	rows := normItems(request.Items)
	merged, me := checkedMerge(rows)
	t, c, r, oe := checkOptions(request.Tier, request.Coupon, request.Region)
	return resolveQuote(merged, me, oe, t, c, r)
}

func resolveQuote(i map[string]checkedItem, e, o *QuoteError, t, c string, r rates) Outcome {
	return resolveIssue(i, firstError(e, o), t, c, r)
}
func resolveIssue(i map[string]checkedItem, e *QuoteError, t, c string, r rates) Outcome {
	if e != nil {
		return errOutcome(e)
	}
	return quoteFromItems(i, t, c, r)
}
func firstError(first, second *QuoteError) *QuoteError {
	if first != nil {
		return first
	}
	return second
}
func errOutcome(err *QuoteError) Outcome { return Outcome{Err: err} }
func checkedMerge(rows []RawItem) (map[string]checkedItem, *QuoteError) {
	if err := checkItems(rows); err != nil {
		return nil, err
	}
	return mergeRows(rows, make(map[string]checkedItem, len(rows)))
}
func normItems(items []RawItem) (rows []RawItem) {
	for _, row := range items {
		rows = append(rows, normItem(row))
	}
	return
}
func normItem(row RawItem) RawItem {
	row.Sku = textNorm(row.Sku)
	return row
}
func textNorm(value string) string { return upper(strings.TrimSpace(value)) }
func upper(value string) string    { return strings.ToUpper(value) }
func checkItems(rows []RawItem) *QuoteError {
	if err := itemCountError(len(rows)); err != nil {
		return err
	}
	return checkRows(rows)
}
func checkRows(rows []RawItem) *QuoteError {
	index := slices.IndexFunc(rows, invalidRow)
	return errorAt(index, rows)
}
func invalidRow(row RawItem) bool { return rowCode(row) != "" }
func errorAt(index int, rows []RawItem) *QuoteError {
	if index < 0 {
		return nil
	}
	return errOf(rowCode(rows[index]), index)
}
func itemCountError(count int) *QuoteError {
	return firstError(
		errorWhen(count == 0, "EMPTY_ORDER", -1),
		errorWhen(count > 50, "TOO_MANY_ITEMS", -1),
	)
}
func errorWhen(bad bool, code string, index int) *QuoteError {
	if !bad {
		return nil
	}
	return errOf(code, index)
}
func rowCode(row RawItem) string {
	return codeFor(skuCode(row.Sku), quantityCode(row.Qty), priceCode(row.Price))
}
func codeFor(sku, quantity, price string) string {
	if sku != "" {
		return sku
	}
	return afterSKU(quantity, price)
}
func afterSKU(quantity, price string) string {
	if quantity != "" {
		return quantity
	}
	return price
}
func skuCode(value string) string     { return codeWhen(!skuOK(value), "BAD_SKU") }
func quantityCode(value int64) string { return codeWhen(!qtyOK(value), "BAD_QTY") }
func priceCode(value string) string {
	bad := !priceRule.MatchString(value) || priceValue(value) == 0
	return codeWhen(bad, "BAD_PRICE")
}
func codeWhen(bad bool, code string) string {
	if !bad {
		return ""
	}
	return code
}
func skuOK(value string) bool { return skuRule.MatchString(value) }
func qtyOK(value int64) bool  { return value >= 1 && value <= 1000 }
func errOf(code string, i int) *QuoteError {
	if i < 0 {
		return &QuoteError{Code: code}
	}
	return &QuoteError{Code: code, Index: &i}
}
func priceValue(text string) int64 {
	whole, fraction, _ := strings.Cut(text, ".")
	units, _ := strconv.ParseInt(whole, 10, 64)
	minor, _ := strconv.ParseInt(fraction+strings.Repeat("0", 2-len(fraction)), 10, 64)
	return units*100 + minor
}
func mergeRows(rows []RawItem, items map[string]checkedItem) (map[string]checkedItem, *QuoteError) {
	return items, mergeIssues(rows, items)
}
func mergeIssues(rows []RawItem, items map[string]checkedItem) (issue *QuoteError) {
	for i, row := range rows {
		issue = firstError(issue, storeItem(items, row, i))
	}
	return
}
func storeItem(items map[string]checkedItem, row RawItem, i int) *QuoteError {
	old := items[row.Sku]
	err := mergeValues(&old, row, priceValue(row.Price), i)
	items[row.Sku] = old
	return err
}
func mergeValues(old *checkedItem, row RawItem, value int64, i int) *QuoteError {
	priceErr := errorWhen(old.qty > 0 && old.cents != value, "PRICE_CONFLICT", i)
	old.qty += row.Qty
	old.sku, old.cents = row.Sku, value
	return firstError(priceErr, errorWhen(old.qty > 1000, "BAD_QTY", i))
}
func checkOptions(tier, coupon, region string) (string, string, rates, *QuoteError) {
	return normalizedOptions(tierNorm(tier), textNorm(coupon), textNorm(region))
}
func normalizedOptions(tier, coupon, region string) (string, string, rates, *QuoteError) {
	r, ok := ratesFor(region)
	err := optionError(tier, coupon, ok)
	return tier, coupon, r, err
}
func tierNorm(value string) string { return strings.ToLower(strings.TrimSpace(value)) }
func optionError(t, c string, regionOK bool) *QuoteError {
	return firstError(tierAndCouponError(t, c), regionError(regionOK))
}
func tierAndCouponError(tier, coupon string) *QuoteError {
	return firstError(tierError(tier), couponError(coupon))
}
func tierError(tier string) *QuoteError {
	return errorWhen(!tierOK(tier), "BAD_TIER", -1)
}
func couponError(coupon string) *QuoteError {
	return errorWhen(coupon != "" && !couponOK(coupon), "BAD_COUPON", -1)
}
func regionError(regionOK bool) *QuoteError {
	return errorWhen(!regionOK, "BAD_REGION", -1)
}
func tierOK(value string) bool { return value == "basic" || value == "silver" || value == "gold" }
func couponOK(value string) bool {
	if value == "FREESHIP" {
		return true
	}
	return couponNumber(value, "PCT", 50) || couponNumber(value, "FIXED", 500)
}
func couponNumber(value, prefix string, limit int) bool {
	suffix := strings.TrimPrefix(value, prefix)
	n, err := strconv.Atoi(suffix)
	return strings.HasPrefix(value, prefix) && err == nil &&
		n >= 1 && n <= limit && strconv.Itoa(n) == suffix
}
func ratesFor(region string) (rates, bool) {
	value, ok := rateTable[region]
	return value, ok
}

var rateTable = map[string]rates{
	"EU":   {2000, 800, 10000},
	"US":   {700, 500, 7500},
	"ASIA": {1000, 1200, 15000},
}

func lineSet(items map[string]checkedItem) ([]Line, int64) {
	keys := keysOf(items)
	return priceRows(keys, items)
}
func priceRows(keys []string, items map[string]checkedItem) (lines []Line, total int64) {
	for _, key := range keys {
		lines, total = addLine(lines, total, items[key])
	}
	return
}
func addLine(lines []Line, total int64, row checkedItem) ([]Line, int64) {
	line := lineOf(row)
	return append(lines, line), total + line.LineCents
}
func keysOf(items map[string]checkedItem) []string { return sortKeys(keySlice(items)) }
func keySlice(items map[string]checkedItem) (keys []string) {
	for key := range items {
		keys = append(keys, key)
	}
	return
}
func sortKeys(keys []string) []string {
	sort.Strings(keys)
	return keys
}
func lineOf(row checkedItem) Line { return Line{row.sku, row.qty, row.cents, row.qty * row.cents} }
func quoteFromItems(items map[string]checkedItem, tier, coupon string, region rates) Outcome {
	lines, subtotal := lineSet(items)
	return priceQuote(lines, subtotal, tier, coupon, region)
}
func priceQuote(lines []Line, subtotal int64, tier, coupon string, region rates) Outcome {
	tierCut, couponCut, net := discountParts(subtotal, tier, coupon)
	shipping := shippingFor(net, coupon, region)
	tax := taxFor(net, region)
	return makeQuote(lines, subtotal, tierCut, couponCut, net, shipping, tax)
}
func discountParts(subtotal int64, tier, coupon string) (tierCut, couponCut, net int64) {
	tierCut = tierDiscount(subtotal, tier)
	couponCut = couponDiscount(subtotal-tierCut, coupon)
	net = subtotal - tierCut - couponCut
	return
}
func makeQuote(lines []Line, subtotal, tierCut, couponCut, net, shipping, tax int64) Outcome {
	applied := serviceLabels(appliedFor(tierCut, couponCut), shipping, tax)
	total := net + shipping + tax
	result := Quote{lines, subtotal, tierCut, couponCut, shipping, tax, total, applied}
	return Outcome{Quote: &result}
}
func tierDiscount(value int64, tier string) int64 { return round(value, tierRate(tier), 10000) }
func taxFor(net int64, region rates) int64        { return round(net, region.tax, 10000) }
func tierRate(tier string) int64                  { return tierRates[tier] }

var tierRates = map[string]int64{"silver": 500, "gold": 1000}

func couponDiscount(net int64, coupon string) int64 {
	percent, _ := strconv.ParseInt(strings.TrimPrefix(coupon, "PCT"), 10, 64)
	fixed, _ := strconv.ParseInt(strings.TrimPrefix(coupon, "FIXED"), 10, 64)
	return round(net, percent, 100) + min(net, fixed*100)
}
func min(left, right int64) int64 {
	if left < right {
		return left
	}
	return right
}
func shippingFor(net int64, coupon string, region rates) int64 {
	return shippingAmount(coupon == "FREESHIP" || net >= region.threshold, region.shipping)
}
func shippingAmount(waived bool, amount int64) int64 {
	if waived {
		return 0
	}
	return amount
}
func appliedFor(tierCut, couponCut int64) []string {
	applied := appendWhen(nil, tierCut > 0, "tier")
	return appendWhen(applied, couponCut > 0, "coupon")
}
func appendWhen(labels []string, include bool, label string) []string {
	if include {
		return append(labels, label)
	}
	return labels
}
func serviceLabels(applied []string, shipping, tax int64) []string {
	applied = appendWhen(applied, shipping == 0, "free-shipping")
	applied = appendWhen(applied, tax > 0, "tax")
	return applied
}
func round(value, rate, base int64) int64 { return (value*rate*2 + base) / (2 * base) }
