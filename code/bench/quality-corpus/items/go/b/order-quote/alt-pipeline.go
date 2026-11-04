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

type quoteFlow struct {
	request                                          Request
	rows                                             []flowRow
	items                                            map[string]flowRow
	tier, coupon                                     string
	rate                                             int64
	region                                           flowRegion
	lines                                            []Line
	subtotal, tierCut, couponCut, net, shipping, tax int64
}
type flowRow struct {
	sku        string
	qty, cents int64
}
type flowRegion struct{ tax, shipping, threshold int64 }

var pipelineSKU = regexp.MustCompile(`^[A-Z0-9-]{3,12}$`)
var pipelinePrice = regexp.MustCompile(`^([0-9]{1,6})(?:\.([0-9]{1,2}))?$`)
var flowTariffs = map[string]flowRegion{
	"EU":   {2000, 800, 10000},
	"US":   {700, 500, 7500},
	"ASIA": {1000, 1200, 15000},
}

// Solution carries a request through a sequence of validation and pricing passes.
func Solution(request Request) Outcome {
	flow := &quoteFlow{request: request}
	if issue := runFlow(flow); issue != nil {
		return Outcome{Err: issue}
	}
	priceFlow(flow)
	return Outcome{Quote: finishFlow(flow)}
}

func runFlow(flow *quoteFlow) *QuoteError {
	if issue := sizeFlow(flow); issue != nil {
		return issue
	}
	if issue := readFlow(flow); issue != nil {
		return issue
	}
	if issue := mergeFlow(flow); issue != nil {
		return issue
	}
	return optionsFlow(flow)
}

func sizeFlow(flow *quoteFlow) *QuoteError {
	if len(flow.request.Items) == 0 {
		return &QuoteError{Code: "EMPTY_ORDER"}
	}
	if len(flow.request.Items) > 50 {
		return &QuoteError{Code: "TOO_MANY_ITEMS"}
	}
	return nil
}

func readFlow(flow *quoteFlow) *QuoteError {
	for i, row := range flow.request.Items {
		sku := strings.ToUpper(strings.TrimSpace(row.Sku))
		if !pipelineSKU.MatchString(sku) {
			return &QuoteError{Code: "BAD_SKU", Index: &i}
		}
		if row.Qty < 1 || row.Qty > 1000 {
			return &QuoteError{Code: "BAD_QTY", Index: &i}
		}
		cents, ok := flowCents(row.Price)
		if !ok {
			return &QuoteError{Code: "BAD_PRICE", Index: &i}
		}
		flow.rows = append(flow.rows, flowRow{sku, row.Qty, cents})
	}
	return nil
}

func flowCents(text string) (int64, bool) {
	parts := pipelinePrice.FindStringSubmatch(text)
	if parts == nil {
		return 0, false
	}
	cents, _ := strconv.ParseInt(parts[1]+(parts[2] + "00")[:2], 10, 64)
	return cents, cents > 0
}

func mergeFlow(flow *quoteFlow) *QuoteError {
	flow.items = make(map[string]flowRow, len(flow.rows))
	for i, row := range flow.rows {
		prior, found := flow.items[row.sku]
		if !found {
			flow.items[row.sku] = row
			continue
		}
		combined, issue := mergeOne(prior, row, i)
		if issue != nil {
			return issue
		}
		flow.items[row.sku] = combined
	}
	return nil
}

func mergeOne(prior, row flowRow, index int) (flowRow, *QuoteError) {
	if prior.cents != row.cents {
		return prior, &QuoteError{Code: "PRICE_CONFLICT", Index: &index}
	}
	if prior.qty+row.qty > 1000 {
		return prior, &QuoteError{Code: "BAD_QTY", Index: &index}
	}
	prior.qty += row.qty
	return prior, nil
}

func optionsFlow(flow *quoteFlow) *QuoteError {
	flow.tier = strings.ToLower(strings.TrimSpace(flow.request.Tier))
	flow.coupon = strings.ToUpper(strings.TrimSpace(flow.request.Coupon))
	region := strings.ToUpper(strings.TrimSpace(flow.request.Region))
	var known bool
	if flow.rate, known = flowTierRate(flow.tier); !known {
		return &QuoteError{Code: "BAD_TIER"}
	}
	if !flowCouponValid(flow.coupon) {
		return &QuoteError{Code: "BAD_COUPON"}
	}
	if flow.region, known = flowTariffs[region]; !known {
		return &QuoteError{Code: "BAD_REGION"}
	}
	return nil
}

func flowTierRate(tier string) (int64, bool) {
	switch tier {
	case "basic":
		return 0, true
	case "silver":
		return 500, true
	case "gold":
		return 1000, true
	}
	return 0, false
}

func flowCouponValid(coupon string) bool {
	if coupon == "" || coupon == "FREESHIP" {
		return true
	}
	digits, limit := strings.TrimPrefix(coupon, "FIXED"), 500
	if percent, ok := strings.CutPrefix(coupon, "PCT"); ok {
		digits, limit = percent, 50
	} else if digits == coupon {
		return false
	}
	plain := digits != "" && digits[0] != '0' && len(digits) <= 3
	if !plain || strings.Trim(digits, "0123456789") != "" {
		return false
	}
	n, _ := strconv.Atoi(digits)
	return n <= limit
}

func priceFlow(flow *quoteFlow) {
	flow.lines = sortedFlowLines(flow.items)
	for _, line := range flow.lines {
		flow.subtotal += line.LineCents
	}
	flow.tierCut = roundedFraction(flow.subtotal*flow.rate, 10000)
	afterTier := flow.subtotal - flow.tierCut
	flow.couponCut = flowCouponCut(afterTier, flow.coupon)
	flow.net = afterTier - flow.couponCut
	flow.shipping = flow.region.shipping
	if flow.coupon == "FREESHIP" || flow.net >= flow.region.threshold {
		flow.shipping = 0
	}
	flow.tax = roundedFraction(flow.net*flow.region.tax, 10000)
}

func sortedFlowLines(items map[string]flowRow) []Line {
	lines := make([]Line, 0, len(items))
	for sku, row := range items {
		lines = append(lines, Line{sku, row.qty, row.cents, row.qty * row.cents})
	}
	sort.Slice(lines, func(a, b int) bool { return lines[a].Sku < lines[b].Sku })
	return lines
}

func flowCouponCut(amount int64, coupon string) int64 {
	if digits, ok := strings.CutPrefix(coupon, "PCT"); ok {
		percent, _ := strconv.ParseInt(digits, 10, 64)
		return roundedFraction(amount*percent, 100)
	}
	if digits, ok := strings.CutPrefix(coupon, "FIXED"); ok {
		fixed, _ := strconv.ParseInt(digits, 10, 64)
		if fixed*100 > amount {
			return amount
		}
		return fixed * 100
	}
	return 0
}

func roundedFraction(numerator, denominator int64) int64 {
	q, r := numerator/denominator, numerator%denominator
	if r >= (denominator+1)/2 {
		q++
	}
	return q
}

func finishFlow(flow *quoteFlow) *Quote {
	return &Quote{
		Lines: flow.lines, Subtotal: flow.subtotal, TierDiscount: flow.tierCut,
		CouponDiscount: flow.couponCut, Shipping: flow.shipping, Tax: flow.tax,
		Total: flow.net + flow.shipping + flow.tax, Applied: flowLabels(flow),
	}
}

func flowLabels(flow *quoteFlow) []string {
	labels := make([]string, 0, 4)
	for _, label := range []struct {
		enabled bool
		text    string
	}{
		{flow.tierCut > 0, "tier"},
		{flow.couponCut > 0, "coupon"},
		{flow.shipping == 0, "free-shipping"},
		{flow.tax > 0, "tax"},
	} {
		if label.enabled {
			labels = append(labels, label.text)
		}
	}
	return labels
}
