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
	rows := normalizeItems(request.Items)
	merged, me := validatedMerge(rows)
	t, c, r, oe := validateOptions(request.Tier, request.Coupon, request.Region)
	return quoteWithIssues(merged, me, oe, t, c, r)
}

func quoteWithIssues(i map[string]checkedItem, e, o *QuoteError,
	t, c string, r rates) Outcome {
	return returnForIssue(i, earlierError(e, o), t, c, r)
}
func returnForIssue(i map[string]checkedItem, e *QuoteError, t, c string, r rates) Outcome {
	if e != nil {
		return errorOutcome(e)
	}
	return buildQuoteFromItems(i, t, c, r)
}
func earlierError(first, second *QuoteError) *QuoteError {
	if first != nil {
		return first
	}
	return second
}
func errorOutcome(err *QuoteError) Outcome { return Outcome{Err: err} }
func validatedMerge(rows []RawItem) (map[string]checkedItem, *QuoteError) {
	if err := validateItems(rows); err != nil {
		return nil, err
	}
	return mergeInOrder(rows, make(map[string]checkedItem, len(rows)))
}
func normalizeItems(items []RawItem) (rows []RawItem) {
	for _, row := range items {
		rows = append(rows, normalizedItem(row))
	}
	return
}
func normalizedItem(row RawItem) RawItem {
	row.Sku = normalizeText(row.Sku)
	return row
}
func normalizeText(value string) string  { return uppercaseASCII(strings.TrimSpace(value)) }
func uppercaseASCII(value string) string { return strings.ToUpper(value) }
func validateItems(rows []RawItem) *QuoteError {
	if err := validateItemCount(len(rows)); err != nil {
		return err
	}
	return validateRows(rows)
}
func validateRows(rows []RawItem) *QuoteError {
	index := slices.IndexFunc(rows, isInvalidItem)
	return itemErrorAt(index, rows)
}
func isInvalidItem(row RawItem) bool { return validationCode(row) != "" }
func itemErrorAt(index int, rows []RawItem) *QuoteError {
	if index < 0 {
		return nil
	}
	return quoteError(validationCode(rows[index]), index)
}
func validateItemCount(count int) *QuoteError {
	return earlierError(
		errorForCondition(count == 0, "EMPTY_ORDER", -1),
		errorForCondition(count > 50, "TOO_MANY_ITEMS", -1),
	)
}
func errorForCondition(bad bool, code string, index int) *QuoteError {
	if !bad {
		return nil
	}
	return quoteError(code, index)
}
func validationCode(row RawItem) string {
	return issueCode(skuProblem(row.Sku), quantityProblem(row.Qty), priceProblem(row.Price))
}
func issueCode(sku, quantity, price string) string {
	if sku != "" {
		return sku
	}
	return quantityOrPriceIssue(quantity, price)
}
func quantityOrPriceIssue(quantity, price string) string {
	if quantity != "" {
		return quantity
	}
	return price
}
func skuProblem(value string) string { return codeForValidity(!validSKU(value), "BAD_SKU") }
func quantityProblem(value int64) string {
	return codeForValidity(!validQuantity(value), "BAD_QTY")
}
func priceProblem(value string) string {
	bad := !priceRule.MatchString(value) || centsForPrice(value) == 0
	return codeForValidity(bad, "BAD_PRICE")
}
func codeForValidity(bad bool, code string) string {
	if !bad {
		return ""
	}
	return code
}
func validSKU(value string) bool     { return skuRule.MatchString(value) }
func validQuantity(value int64) bool { return value >= 1 && value <= 1000 }
func quoteError(code string, i int) *QuoteError {
	if i < 0 {
		return &QuoteError{Code: code}
	}
	return &QuoteError{Code: code, Index: &i}
}
func centsForPrice(text string) int64 {
	whole, fraction, _ := strings.Cut(text, ".")
	units, _ := strconv.ParseInt(whole, 10, 64)
	minor, _ := strconv.ParseInt(fraction+strings.Repeat("0", 2-len(fraction)), 10, 64)
	return units*100 + minor
}
func mergeInOrder(rows []RawItem, items map[string]checkedItem) (
	map[string]checkedItem, *QuoteError,
) {
	return items, collectMergeIssue(rows, items)
}
func collectMergeIssue(rows []RawItem, items map[string]checkedItem) (issue *QuoteError) {
	for i, row := range rows {
		issue = earlierError(issue, mergeItemAt(items, row, i))
	}
	return
}
func mergeItemAt(items map[string]checkedItem, row RawItem, i int) *QuoteError {
	old := items[row.Sku]
	err := addPriceAndQuantity(&old, row, centsForPrice(row.Price), i)
	items[row.Sku] = old
	return err
}
func addPriceAndQuantity(old *checkedItem, row RawItem, value int64, i int) *QuoteError {
	priceErr := errorForCondition(old.qty > 0 && old.cents != value, "PRICE_CONFLICT", i)
	old.qty += row.Qty
	old.sku, old.cents = row.Sku, value
	return earlierError(priceErr, errorForCondition(old.qty > 1000, "BAD_QTY", i))
}
func validateOptions(tier, coupon, region string) (string, string, rates, *QuoteError) {
	return checkedOptions(normalizeTier(tier), normalizeText(coupon), normalizeText(region))
}
func checkedOptions(tier, coupon, region string) (string, string, rates, *QuoteError) {
	r, ok := regionRates(region)
	err := optionValidationError(tier, coupon, ok)
	return tier, coupon, r, err
}
func normalizeTier(value string) string { return strings.ToLower(strings.TrimSpace(value)) }
func optionValidationError(t, c string, regionOK bool) *QuoteError {
	return earlierError(tierCouponProblem(t, c), regionValidationError(regionOK))
}
func tierCouponProblem(tier, coupon string) *QuoteError {
	return earlierError(tierValidationError(tier), couponValidationError(coupon))
}
func tierValidationError(tier string) *QuoteError {
	return errorForCondition(!validTier(tier), "BAD_TIER", -1)
}
func couponValidationError(coupon string) *QuoteError {
	return errorForCondition(coupon != "" && !validCoupon(coupon), "BAD_COUPON", -1)
}
func regionValidationError(regionOK bool) *QuoteError {
	return errorForCondition(!regionOK, "BAD_REGION", -1)
}
func validTier(value string) bool {
	return value == "basic" || value == "silver" || value == "gold"
}
func validCoupon(value string) bool {
	if value == "FREESHIP" {
		return true
	}
	return validCouponNumber(value, "PCT", 50) || validCouponNumber(value, "FIXED", 500)
}
func validCouponNumber(value, prefix string, limit int) bool {
	suffix := strings.TrimPrefix(value, prefix)
	n, err := strconv.Atoi(suffix)
	return strings.HasPrefix(value, prefix) && err == nil &&
		n >= 1 && n <= limit && strconv.Itoa(n) == suffix
}
func regionRates(region string) (rates, bool) {
	value, ok := rateTable[region]
	return value, ok
}

var rateTable = map[string]rates{
	"EU":   {2000, 800, 10000},
	"US":   {700, 500, 7500},
	"ASIA": {1000, 1200, 15000},
}

func priceSortedItems(items map[string]checkedItem) ([]Line, int64) {
	keys := sortedSKUs(items)
	return pricedRows(keys, items)
}
func pricedRows(keys []string, items map[string]checkedItem) (lines []Line, total int64) {
	for _, key := range keys {
		lines, total = appendLineAmount(lines, total, items[key])
	}
	return
}
func appendLineAmount(lines []Line, total int64, row checkedItem) ([]Line, int64) {
	line := lineFromItem(row)
	return append(lines, line), total + line.LineCents
}
func sortedSKUs(items map[string]checkedItem) []string { return sortSKUs(collectSKUs(items)) }
func collectSKUs(items map[string]checkedItem) (keys []string) {
	for key := range items {
		keys = append(keys, key)
	}
	return
}
func sortSKUs(keys []string) []string {
	sort.Strings(keys)
	return keys
}
func lineFromItem(row checkedItem) Line {
	return Line{row.sku, row.qty, row.cents, row.qty * row.cents}
}
func buildQuoteFromItems(items map[string]checkedItem, tier, coupon string, region rates) Outcome {
	lines, subtotal := priceSortedItems(items)
	return finishQuote(lines, subtotal, tier, coupon, region)
}
func finishQuote(lines []Line, subtotal int64, tier, coupon string, region rates) Outcome {
	tierCut, couponCut, net := discountAmounts(subtotal, tier, coupon)
	shipping := shippingCharge(net, coupon, region)
	tax := regionalTax(net, region)
	return assembleQuote(lines, subtotal, tierCut, couponCut, net, shipping, tax)
}
func discountAmounts(subtotal int64, tier, coupon string) (tierCut, couponCut, net int64) {
	tierCut = discountForTier(subtotal, tier)
	couponCut = discountForCoupon(subtotal-tierCut, coupon)
	net = subtotal - tierCut - couponCut
	return
}
func assembleQuote(lines []Line, subtotal, tierCut, couponCut, net, shipping, tax int64) Outcome {
	applied := shippingAndTaxLabels(discountLabels(tierCut, couponCut), shipping, tax)
	total := net + shipping + tax
	result := Quote{lines, subtotal, tierCut, couponCut, shipping, tax, total, applied}
	return Outcome{Quote: &result}
}
func discountForTier(value int64, tier string) int64 {
	return roundHalfUp(value, basisPointsForTier(tier), 10000)
}
func regionalTax(net int64, region rates) int64 { return roundHalfUp(net, region.tax, 10000) }
func basisPointsForTier(tier string) int64      { return tierRates[tier] }

var tierRates = map[string]int64{"silver": 500, "gold": 1000}

func discountForCoupon(net int64, coupon string) int64 {
	percent, _ := strconv.ParseInt(strings.TrimPrefix(coupon, "PCT"), 10, 64)
	fixed, _ := strconv.ParseInt(strings.TrimPrefix(coupon, "FIXED"), 10, 64)
	return roundHalfUp(net, percent, 100) + cappedAmount(net, fixed*100)
}
func cappedAmount(left, right int64) int64 {
	if left < right {
		return left
	}
	return right
}
func shippingCharge(net int64, coupon string, region rates) int64 {
	return chargeAfterWaiver(coupon == "FREESHIP" || net >= region.threshold, region.shipping)
}
func chargeAfterWaiver(waived bool, amount int64) int64 {
	if waived {
		return 0
	}
	return amount
}
func discountLabels(tierCut, couponCut int64) []string {
	applied := appendIf(nil, tierCut > 0, "tier")
	return appendIf(applied, couponCut > 0, "coupon")
}
func appendIf(labels []string, include bool, label string) []string {
	if include {
		return append(labels, label)
	}
	return labels
}
func shippingAndTaxLabels(applied []string, shipping, tax int64) []string {
	applied = appendIf(applied, shipping == 0, "free-shipping")
	applied = appendIf(applied, tax > 0, "tax")
	return applied
}
func roundHalfUp(value, rate, base int64) int64 { return (value*rate*2 + base) / (2 * base) }
