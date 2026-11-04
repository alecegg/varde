type Request = {
  items: { sku: string; qty: number; price: string }[];
  tier: string;
  coupon: string;
  region: string;
};

/** Quote normalized order lines with tier, coupon, shipping, tax, and applied adjustments. */
export function solution(request: Request) {
  const items = request.items;
  const tierText = request.tier.trim();
  const tier = tierText.toLowerCase();
  const couponText = request.coupon.trim();
  const coupon = couponText.replace(/[a-z]/g, (letter) => letter.toUpperCase());
  const regionText = request.region.trim();
  const region = regionText.replace(/[a-z]/g, (letter) => letter.toUpperCase());
  if (items.length === 0) return { error: "EMPTY_ORDER", index: null };
  if (items.length > 50) return { error: "TOO_MANY_ITEMS", index: null };

  const checked: { sku: string; qty: number; cents: number }[] = [];
  for (let index = 0; index < items.length; index++) {
    const item = items[index];
    const skuText = item.sku.trim();
    const sku = skuText.replace(/[a-z]/g, (letter) => letter.toUpperCase());
    const skuIsValid = /^[A-Z0-9-]{3,12}$/.test(sku);
    if (!skuIsValid) return { error: "BAD_SKU", index };
    const quantityIsInteger = Number.isInteger(item.qty);
    const quantityIsInRange = item.qty >= 1 && item.qty <= 1000;
    if (!quantityIsInteger || !quantityIsInRange) return { error: "BAD_QTY", index };
    const priceText = item.price;
    const priceHasValidShape = /^[0-9]{1,6}(\.[0-9]{1,2})?$/.test(priceText);
    if (!priceHasValidShape) return { error: "BAD_PRICE", index };
    const priceParts = priceText.split(".");
    const whole = priceParts[0];
    const fraction = priceParts[1] ?? "";
    const wholeDollars = Number(whole);
    const wholeCents = wholeDollars * 100;
    const fractionText = (fraction + "00").slice(0, 2);
    const fractionCents = Number(fractionText);
    const cents = wholeCents + fractionCents;
    if (cents === 0) return { error: "BAD_PRICE", index };
    checked.push({ sku, qty: item.qty, cents });
  }

  const merged = new Map<string, { qty: number; cents: number }>();
  for (let index = 0; index < checked.length; index++) {
    const item = checked[index];
    const prior = merged.get(item.sku);
    if (!prior) {
      merged.set(item.sku, { qty: item.qty, cents: item.cents });
      continue;
    }
    if (prior.cents !== item.cents) return { error: "PRICE_CONFLICT", index };
    const combinedQuantity = prior.qty + item.qty;
    prior.qty = combinedQuantity;
    const mergedQuantityIsTooLarge = combinedQuantity > 1000;
    if (mergedQuantityIsTooLarge) return { error: "BAD_QTY", index };
  }

  if (!(tier === "basic" || tier === "silver" || tier === "gold")) {
    return { error: "BAD_TIER", index: null };
  }
  const couponIsEmpty = coupon.length === 0;
  const couponIsFreeShipping = coupon === "FREESHIP";
  const couponMatch = /^(PCT|FIXED)([1-9][0-9]*)$/.exec(coupon);
  const couponKind = couponMatch?.[1] ?? "";
  const couponAmountText = couponMatch?.[2] ?? "";
  const couponAmount = Number(couponAmountText);
  const couponLimit = couponKind === "PCT" ? 50 : 500;
  const couponHasValidFormat = couponMatch !== null;
  const couponAmountIsWithinLimit = couponAmount <= couponLimit;
  const couponAmountIsValid = couponHasValidFormat && couponAmountIsWithinLimit;
  const couponOk = couponIsEmpty || couponIsFreeShipping || couponAmountIsValid;
  if (!couponOk) return { error: "BAD_COUPON", index: null };
  const regions: Record<string, { taxRate: number; shipping: number; threshold: number }> = {
    EU: { taxRate: 2000, shipping: 800, threshold: 10000 },
    US: { taxRate: 700, shipping: 500, threshold: 7500 },
    ASIA: { taxRate: 1000, shipping: 1200, threshold: 15000 },
  };
  const regionIsValid = Object.hasOwn(regions, region);
  if (!regionIsValid) return { error: "BAD_REGION", index: null };

  const sortedItems = [...merged.entries()].sort(([left], [right]) =>
    left < right ? -1 : left > right ? 1 : 0,
  );
  const lines: { sku: string; qty: number; unit_cents: number; line_cents: number }[] = [];
  let subtotal = 0;
  for (const [sku, item] of sortedItems) {
    const quantity = item.qty;
    const unitCents = item.cents;
    const lineCents = quantity * unitCents;
    const line = { sku, qty: quantity, unit_cents: unitCents, line_cents: lineCents };
    lines.push(line);
    subtotal += lineCents;
  }
  const tierRate = tier === "gold" ? 1000 : tier === "silver" ? 500 : 0;
  const tierProduct = subtotal * tierRate;
  const tierDenominator = 10000;
  const tierWholeDiscount = Math.floor(tierProduct / tierDenominator);
  const tierRemainder = tierProduct % tierDenominator;
  const doubledTierRemainder = 2 * tierRemainder;
  const tierRoundThreshold = tierDenominator;
  const tierRoundsUp = doubledTierRemainder >= tierRoundThreshold;
  const tierDiscount = tierWholeDiscount + Number(tierRoundsUp);
  const afterTier = subtotal - tierDiscount;
  let couponDiscount = 0;
  if (coupon.startsWith("PCT")) {
    const percentageText = coupon.slice(3);
    const percentage = Number(percentageText);
    const couponProduct = afterTier * percentage;
    const couponDenominator = 100;
    const couponWholeDiscount = Math.floor(couponProduct / couponDenominator);
    const couponRemainder = couponProduct % couponDenominator;
    const doubledCouponRemainder = 2 * couponRemainder;
    const couponRoundThreshold = couponDenominator;
    const couponRoundsUp = doubledCouponRemainder >= couponRoundThreshold;
    couponDiscount = couponWholeDiscount + Number(couponRoundsUp);
  } else if (coupon.startsWith("FIXED")) {
    const fixedDollarText = coupon.slice(5);
    const fixedDollars = Number(fixedDollarText);
    const fixedCents = fixedDollars * 100;
    couponDiscount = Math.min(fixedCents, afterTier);
  }
  const net = afterTier - couponDiscount;
  const config = regions[region];
  const couponWaivesShipping = couponIsFreeShipping;
  const shippingThreshold = config.threshold;
  const subtotalMeetsShippingThreshold = net >= shippingThreshold;
  const shippingIsWaived = couponWaivesShipping || subtotalMeetsShippingThreshold;
  const regionalShippingCharge = config.shipping;
  const shipping = shippingIsWaived ? 0 : regionalShippingCharge;
  const regionalTaxRate = config.taxRate;
  const taxProduct = net * regionalTaxRate;
  const taxDenominator = 10000;
  const taxWholeAmount = Math.floor(taxProduct / taxDenominator);
  const taxRemainder = taxProduct % taxDenominator;
  const doubledTaxRemainder = 2 * taxRemainder;
  const taxRoundThreshold = taxDenominator;
  const taxRoundsUp = doubledTaxRemainder >= taxRoundThreshold;
  const tax = taxWholeAmount + Number(taxRoundsUp);
  const applied: string[] = [];
  const tierDiscountIsApplied = tierDiscount > 0;
  const couponDiscountIsApplied = couponDiscount > 0;
  const shippingIsFree = shipping === 0;
  const taxIsApplied = tax > 0;
  if (tierDiscountIsApplied) applied.push("tier");
  if (couponDiscountIsApplied) applied.push("coupon");
  if (shippingIsFree) applied.push("free-shipping");
  if (taxIsApplied) applied.push("tax");
  const merchandiseTotal = net + shipping;
  const total = merchandiseTotal + tax;
  return {
    lines,
    subtotal,
    tier_discount: tierDiscount,
    coupon_discount: couponDiscount,
    shipping,
    tax,
    total,
    applied,
  };
}
