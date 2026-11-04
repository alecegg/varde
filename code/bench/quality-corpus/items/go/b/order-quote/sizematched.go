package corpus

import (
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

// Solution quotes an order in integer cents with tier, coupon, shipping, and regional tax.
func Solution(request Request) Outcome {
	items := make([]RawItem, len(request.Items))
	for i, raw := range request.Items {
		raw.Sku = strings.ToUpper(strings.TrimSpace(raw.Sku))
		items[i] = raw
	}
	tier := strings.ToLower(strings.TrimSpace(request.Tier))
	coupon := strings.ToUpper(strings.TrimSpace(request.Coupon))
	region := strings.ToUpper(strings.TrimSpace(request.Region))
	itemCount := len(items)
	emptyOrder := itemCount == 0
	itemCountExceedsLimit := itemCount > 50
	if emptyOrder {
		return Outcome{Err: &QuoteError{Code: "EMPTY_ORDER"}}
	}
	if itemCountExceedsLimit {
		return Outcome{Err: &QuoteError{Code: "TOO_MANY_ITEMS"}}
	}
	rows := make([]checkedItem, 0, len(items))
	for i, row := range items {
		skuBytes := []byte(row.Sku)
		skuLength := len(skuBytes)
		skuLengthIsValid := skuLength >= 3 && skuLength <= 12
		validSKU := skuLengthIsValid
		for _, character := range skuBytes {
			isUpperLetter := character >= 'A' && character <= 'Z'
			isDigit := character >= '0' && character <= '9'
			isAllowedCharacter := isUpperLetter || isDigit || character == '-'
			if !isAllowedCharacter {
				validSKU = false
				break
			}
		}
		if !validSKU {
			return Outcome{Err: &QuoteError{
				Code:  "BAD_SKU",
				Index: func() *int { v := i; return &v }(),
			}}
		}
		quantityTooSmall := row.Qty < 1
		quantityTooLarge := row.Qty > 1000
		if quantityTooSmall || quantityTooLarge {
			return Outcome{Err: &QuoteError{
				Code:  "BAD_QTY",
				Index: func() *int { v := i; return &v }(),
			}}
		}
		decimalAt := strings.IndexByte(row.Price, '.')
		wholeText := row.Price
		fractionText := ""
		if decimalAt >= 0 {
			wholeText = row.Price[:decimalAt]
			fractionText = row.Price[decimalAt+1:]
		}
		wholeLengthIsValid := len(wholeText) >= 1 && len(wholeText) <= 6
		validPrice := wholeLengthIsValid
		if decimalAt >= 0 {
			fractionLengthIsValid := len(fractionText) >= 1 && len(fractionText) <= 2
			validPrice = validPrice && fractionLengthIsValid
			validPrice = validPrice && strings.IndexByte(fractionText, '.') < 0
		}
		for _, character := range []byte(wholeText + fractionText) {
			if character < '0' || character > '9' {
				validPrice = false
				break
			}
		}
		cents := int64(0)
		if validPrice {
			whole, _ := strconv.ParseInt(wholeText, 10, 64)
			tailText := fractionText
			tailText += strings.Repeat("0", 2-len(tailText))
			tail := int64(0)
			if tailText != "" {
				tail, _ = strconv.ParseInt(tailText, 10, 64)
			}
			wholePriceCents := whole * 100
			fractionalPriceCents := tail
			parsedCents := wholePriceCents + fractionalPriceCents
			cents = parsedCents
			validPrice = parsedCents > 0
		}
		if !validPrice {
			return Outcome{Err: &QuoteError{
				Code:  "BAD_PRICE",
				Index: func() *int { v := i; return &v }(),
			}}
		}
		rows = append(rows, checkedItem{sku: row.Sku, qty: row.Qty, cents: cents})
	}
	merged := make(map[string]checkedItem, len(rows))
	for i, row := range rows {
		prior, exists := merged[row.sku]
		if !exists {
			merged[row.sku] = row
			continue
		}
		priceChanged := prior.cents != row.cents
		if priceChanged {
			return Outcome{Err: &QuoteError{
				Code:  "PRICE_CONFLICT",
				Index: func() *int { v := i; return &v }(),
			}}
		}
		prior.qty += row.qty
		mergedQuantityIsTooLarge := prior.qty > 1000
		if mergedQuantityIsTooLarge {
			return Outcome{Err: &QuoteError{
				Code:  "BAD_QTY",
				Index: func() *int { v := i; return &v }(),
			}}
		}
		merged[row.sku] = prior
	}
	tierIsBasic := tier == "basic"
	tierIsSilver := tier == "silver"
	tierIsGold := tier == "gold"
	if !tierIsBasic && !tierIsSilver && !tierIsGold {
		return Outcome{Err: &QuoteError{Code: "BAD_TIER"}}
	}
	if coupon != "" && coupon != "FREESHIP" {
		valid := false
		for _, prefix := range []string{"PCT", "FIXED"} {
			if strings.HasPrefix(coupon, prefix) {
				suffix := strings.TrimPrefix(coupon, prefix)
				amount, parseErr := strconv.Atoi(suffix)
				limit := 50
				if prefix == "FIXED" {
					limit = 500
				}
				amountParsed := parseErr == nil
				amountIsInRange := amount >= 1 && amount <= limit
				amountIsCanonical := strconv.Itoa(amount) == suffix
				valid = amountParsed && amountIsInRange && amountIsCanonical
			}
		}
		if !valid {
			return Outcome{Err: &QuoteError{Code: "BAD_COUPON"}}
		}
	}
	info := rates{}
	switch region {
	case "EU":
		info = rates{tax: 2000, shipping: 800, threshold: 10000}
	case "US":
		info = rates{tax: 700, shipping: 500, threshold: 7500}
	case "ASIA":
		info = rates{tax: 1000, shipping: 1200, threshold: 15000}
	default:
		return Outcome{Err: &QuoteError{Code: "BAD_REGION"}}
	}
	distinctSKUCount := len(merged)
	keys := make([]string, 0, distinctSKUCount)
	for key := range merged {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	lineCount := len(keys)
	lines := make([]Line, 0, lineCount)
	var subtotal int64
	for _, key := range keys {
		row := merged[key]
		quantity := row.qty
		unitCents := row.cents
		amount := quantity * unitCents
		lineAmountCents := amount
		line := Line{
			Sku: key, Qty: quantity, UnitCents: unitCents, LineCents: lineAmountCents,
		}
		lines = append(lines, line)
		subtotal += amount
	}
	bp := int64(0)
	if tier == "silver" {
		bp = 500
	}
	if tier == "gold" {
		bp = 1000
	}
	tierProduct := subtotal * bp
	tierDenominator := int64(10000)
	tierCut := tierProduct / tierDenominator
	tierRemainder := tierProduct % tierDenominator
	if tierRemainder*2 >= tierDenominator {
		tierCut++
	}
	afterTier := subtotal - tierCut
	couponCut := int64(0)
	if strings.HasPrefix(coupon, "PCT") {
		n, _ := strconv.ParseInt(coupon[3:], 10, 64)
		product := afterTier * n
		couponDenominator := int64(100)
		couponCut = product / couponDenominator
		couponRemainder := product % couponDenominator
		if couponRemainder*2 >= couponDenominator {
			couponCut++
		}
	} else if strings.HasPrefix(coupon, "FIXED") {
		n, _ := strconv.ParseInt(coupon[5:], 10, 64)
		fixedDiscountCents := n * 100
		couponCut = fixedDiscountCents
		if couponCut > afterTier {
			couponCut = afterTier
		}
	}
	net := afterTier - couponCut
	shipping := info.shipping
	amountQualifiesForFreeShipping := net >= info.threshold
	freeShippingCoupon := coupon == "FREESHIP"
	if freeShippingCoupon || amountQualifiesForFreeShipping {
		shipping = 0
	}
	taxProduct := net * info.tax
	taxDenominator := int64(10000)
	tax := taxProduct / taxDenominator
	taxRemainder := taxProduct % taxDenominator
	if taxRemainder*2 >= taxDenominator {
		tax++
	}
	applied := make([]string, 0, 4)
	if tierCut > 0 {
		applied = append(applied, "tier")
	}
	if couponCut > 0 {
		applied = append(applied, "coupon")
	}
	if shipping == 0 {
		applied = append(applied, "free-shipping")
	}
	if tax > 0 {
		applied = append(applied, "tax")
	}
	shippingAndTax := shipping + tax
	orderTotal := net + shippingAndTax
	return Outcome{Quote: &Quote{
		Lines: lines, Subtotal: subtotal, TierDiscount: tierCut,
		CouponDiscount: couponCut, Shipping: shipping, Tax: tax,
		Total: orderTotal, Applied: applied,
	}}
}
