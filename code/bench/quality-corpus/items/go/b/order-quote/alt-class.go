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

type deskItem struct {
	sku        string
	qty, cents int64
}
type shippingArea struct{ tax, delivery, threshold int64 }
type orderDesk struct {
	rows         []deskItem
	lines        []Line
	tier, coupon string
	area         shippingArea
}

var classSKU = regexp.MustCompile(`^[A-Z0-9-]{3,12}$`)
var classPrice = regexp.MustCompile(`^([0-9]{1,6})(?:\.([0-9]{1,2}))?$`)
var couponShape = regexp.MustCompile(`^(PCT|FIXED)([1-9][0-9]{0,2})$`)
var deskTiers = map[string]int64{"basic": 0, "silver": 500, "gold": 1000}
var deskAreas = map[string]shippingArea{
	"EU":   {2000, 800, 10000},
	"US":   {700, 500, 7500},
	"ASIA": {1000, 1200, 15000},
}

// Solution opens an order desk with validated state and asks it to produce a quote.
func Solution(request Request) Outcome {
	if len(request.Items) == 0 {
		return Outcome{Err: &QuoteError{Code: "EMPTY_ORDER"}}
	}
	if len(request.Items) > 50 {
		return Outcome{Err: &QuoteError{Code: "TOO_MANY_ITEMS"}}
	}
	desk, issue := newOrderDesk(request)
	if issue != nil {
		return Outcome{Err: issue}
	}
	return Outcome{Quote: desk.quote()}
}

func newOrderDesk(request Request) (*orderDesk, *QuoteError) {
	desk := &orderDesk{
		tier:   strings.ToLower(strings.TrimSpace(request.Tier)),
		coupon: strings.ToUpper(strings.TrimSpace(request.Coupon)),
	}
	if issue := desk.validateItems(request.Items); issue != nil {
		return nil, issue
	}
	for i, item := range desk.rows {
		if issue := desk.addItem(item, i); issue != nil {
			return nil, issue
		}
	}
	region := strings.ToUpper(strings.TrimSpace(request.Region))
	if issue := desk.chooseArea(region); issue != nil {
		return nil, issue
	}
	return desk, nil
}

func (desk *orderDesk) validateItems(rows []RawItem) *QuoteError {
	for i, row := range rows {
		row.Sku = strings.ToUpper(strings.TrimSpace(row.Sku))
		if !classSKU.MatchString(row.Sku) {
			return &QuoteError{Code: "BAD_SKU", Index: &i}
		}
		if row.Qty < 1 || row.Qty > 1000 {
			return &QuoteError{Code: "BAD_QTY", Index: &i}
		}
		cents, ok := deskPriceCents(row.Price)
		if !ok {
			return &QuoteError{Code: "BAD_PRICE", Index: &i}
		}
		desk.rows = append(desk.rows, deskItem{row.Sku, row.Qty, cents})
	}
	return nil
}

func deskPriceCents(text string) (int64, bool) {
	parts := classPrice.FindStringSubmatch(text)
	if parts == nil {
		return 0, false
	}
	whole, _ := strconv.ParseInt(parts[1], 10, 64)
	tail, _ := strconv.ParseInt(parts[2]+strings.Repeat("0", 2-len(parts[2])), 10, 64)
	cents := whole*100 + tail
	return cents, cents > 0
}

func (desk *orderDesk) find(sku string) int {
	return sort.Search(len(desk.lines), func(k int) bool { return desk.lines[k].Sku >= sku })
}

func (desk *orderDesk) addItem(item deskItem, index int) *QuoteError {
	pos := desk.find(item.sku)
	if pos < len(desk.lines) && desk.lines[pos].Sku == item.sku {
		return mergeLine(&desk.lines[pos], item, index)
	}
	desk.lines = append(desk.lines, Line{})
	copy(desk.lines[pos+1:], desk.lines[pos:])
	desk.lines[pos] = Line{item.sku, item.qty, item.cents, item.qty * item.cents}
	return nil
}

func mergeLine(line *Line, item deskItem, index int) *QuoteError {
	if line.UnitCents != item.cents {
		return &QuoteError{Code: "PRICE_CONFLICT", Index: &index}
	}
	if line.Qty+item.qty > 1000 {
		return &QuoteError{Code: "BAD_QTY", Index: &index}
	}
	line.Qty += item.qty
	line.LineCents = line.Qty * line.UnitCents
	return nil
}

func (desk *orderDesk) chooseArea(code string) *QuoteError {
	if _, known := deskTiers[desk.tier]; !known {
		return &QuoteError{Code: "BAD_TIER"}
	}
	if !desk.hasCoupon() {
		return &QuoteError{Code: "BAD_COUPON"}
	}
	area, exists := deskAreas[code]
	if !exists {
		return &QuoteError{Code: "BAD_REGION"}
	}
	desk.area = area
	return nil
}

func (desk *orderDesk) hasCoupon() bool {
	if desk.coupon == "" || desk.coupon == "FREESHIP" {
		return true
	}
	parts := couponShape.FindStringSubmatch(desk.coupon)
	if parts == nil {
		return false
	}
	limit := 500
	if parts[1] == "PCT" {
		limit = 50
	}
	amount, _ := strconv.Atoi(parts[2])
	return amount <= limit
}

func (desk *orderDesk) quote() *Quote {
	var subtotal int64
	for _, line := range desk.lines {
		subtotal += line.LineCents
	}
	tierCut := halfUp(subtotal*deskTiers[desk.tier], 10000)
	spendable := subtotal - tierCut
	couponCut := desk.couponReduction(spendable)
	balance := spendable - couponCut
	shipping := desk.area.delivery
	if desk.coupon == "FREESHIP" || balance >= desk.area.threshold {
		shipping = 0
	}
	tax := halfUp(balance*desk.area.tax, 10000)
	return desk.render(subtotal, [5]int64{tierCut, couponCut, balance, shipping, tax})
}

func (desk *orderDesk) couponReduction(amount int64) int64 {
	parts := couponShape.FindStringSubmatch(desk.coupon)
	if parts == nil {
		return 0
	}
	n, _ := strconv.ParseInt(parts[2], 10, 64)
	if parts[1] == "PCT" {
		return halfUp(amount*n, 100)
	}
	if n*100 > amount {
		return amount
	}
	return n * 100
}

func halfUp(numerator, denominator int64) int64 {
	quotient, remainder := numerator/denominator, numerator%denominator
	if remainder*2 >= denominator {
		quotient++
	}
	return quotient
}

func (desk *orderDesk) render(subtotal int64, amounts [5]int64) *Quote {
	tier, coupon, net := amounts[0], amounts[1], amounts[2]
	shipping, tax := amounts[3], amounts[4]
	return &Quote{
		Lines: desk.lines, Subtotal: subtotal, TierDiscount: tier, CouponDiscount: coupon,
		Shipping: shipping, Tax: tax, Total: net + shipping + tax,
		Applied: desk.labels(tier, coupon, shipping, tax),
	}
}

func (desk *orderDesk) labels(tier, coupon, shipping, tax int64) []string {
	labels := make([]string, 0, 4)
	if tier > 0 {
		labels = append(labels, "tier")
	}
	if coupon > 0 {
		labels = append(labels, "coupon")
	}
	if shipping == 0 {
		labels = append(labels, "free-shipping")
	}
	if tax > 0 {
		labels = append(labels, "tax")
	}
	return labels
}
