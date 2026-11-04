type Request = {
  items: { sku: string; qty: number; price: string }[];
  tier: string;
  coupon: string;
  region: string;
};

/** Quote normalized order lines with tier, coupon, shipping, tax, and applied adjustments. */
export function solution(request: Request) {
  const items = request.items.map((item) => ({
    sku: item.sku.trim().replace(/[a-z]/g, (letter) => letter.toUpperCase()),
    qty: item.qty,
    price: item.price,
    cents: 0,
  }));
  const tier = request.tier.trim().toLowerCase();
  const coupon = request.coupon.trim().replace(/[a-z]/g, (letter) => letter.toUpperCase());
  const region = request.region.trim().replace(/[a-z]/g, (letter) => letter.toUpperCase());

  const hasNoItems = items.length === 0;
  if (hasNoItems) return { error: "EMPTY_ORDER", index: null };
  const itemCountExceedsLimit = items.length > 50;
  if (itemCountExceedsLimit) return { error: "TOO_MANY_ITEMS", index: null };

  for (let index = 0; index < items.length; index++) {
    const item = items[index];
    const skuLength = item.sku.length;
    const skuIsLongEnough = skuLength >= 3;
    const skuIsShortEnough = skuLength <= 12;
    const skuLengthIsValid = skuIsLongEnough && skuIsShortEnough;
    const skuCharactersAreValid = /^[A-Z0-9-]+$/.test(item.sku);
    const skuIsValid = skuLengthIsValid && skuCharactersAreValid;
    if (!skuIsValid) return { error: "BAD_SKU", index };
    const quantityIsInteger = Number.isInteger(item.qty);
    const quantityIsPositive = item.qty >= 1;
    const quantityIsAtMostLimit = item.qty <= 1000;
    const quantityIsWithinLimit = quantityIsPositive && quantityIsAtMostLimit;
    if (!quantityIsInteger || !quantityIsPositive || !quantityIsWithinLimit) {
      return { error: "BAD_QTY", index };
    }
    const priceIsText = typeof item.price === "string";
    const pricePattern = /^[0-9]{1,6}(\.[0-9]{1,2})?$/;
    const priceMatchesPattern = priceIsText && pricePattern.test(item.price);
    const priceHasValidFormat = priceMatchesPattern;
    if (!priceHasValidFormat) {
      return { error: "BAD_PRICE", index };
    }
    const priceParts = item.price.split(".");
    const wholeText = priceParts[0];
    const fractionalText = priceParts[1] ?? "";
    const fractionCentsText = (fractionalText + "00").slice(0, 2);
    const wholeDollars = Number(wholeText);
    const centsPerDollar = 100;
    const wholeCents = wholeDollars * centsPerDollar;
    const fractionalCents = Number(fractionCentsText);
    const cents = wholeCents + fractionalCents;
    if (cents === 0) return { error: "BAD_PRICE", index };
    item.cents = cents;
  }

  const merged = new Map<string, { qty: number; cents: number }>();
  for (let index = 0; index < items.length; index++) {
    const item = items[index];
    const prior = merged.get(item.sku);
    if (prior === undefined) {
      merged.set(item.sku, { qty: item.qty, cents: item.cents });
    } else {
      if (prior.cents !== item.cents) return { error: "PRICE_CONFLICT", index };
      prior.qty = prior.qty + item.qty;
      if (prior.qty > 1000) return { error: "BAD_QTY", index };
    }
  }

  const isBasicTier = tier === "basic";
  const isSilverTier = tier === "silver";
  const isGoldTier = tier === "gold";
  const tierIsKnown = isBasicTier || isSilverTier || isGoldTier;
  if (!tierIsKnown) {
    return { error: "BAD_TIER", index: null };
  }
  const couponIsEmpty = coupon.length === 0;
  const couponIsFreeShipping = coupon === "FREESHIP";
  const couponMatch = /^(PCT|FIXED)([1-9][0-9]*)$/.exec(coupon);
  let couponHasValidAmount = false;
  if (couponMatch) {
    const couponAmount = Number(couponMatch[2]);
    let maximumCouponAmount = 500;
    if (couponMatch[1] === "PCT") maximumCouponAmount = 50;
    couponHasValidAmount = couponAmount <= maximumCouponAmount;
  }
  const couponIsKnownCode = couponIsEmpty || couponIsFreeShipping;
  const couponValid = couponIsKnownCode || couponHasValidAmount;
  if (!couponValid) return { error: "BAD_COUPON", index: null };
  const regionIsEurope = region === "EU";
  const regionIsUnitedStates = region === "US";
  const regionIsAsia = region === "ASIA";
  const regionIsKnown = regionIsEurope || regionIsUnitedStates || regionIsAsia;
  if (!regionIsKnown) {
    return { error: "BAD_REGION", index: null };
  }

  const ordered = [...merged.entries()].sort(([left], [right]) =>
    left < right ? -1 : left > right ? 1 : 0,
  );
  const lines = ordered.map(([sku, item]) => ({
    sku,
    qty: item.qty,
    unit_cents: item.cents,
    line_cents: item.qty * item.cents,
  }));
  let subtotal = 0;
  for (const line of lines) {
    const quantity = line.qty;
    const unitPriceInCents = line.unit_cents;
    const extendedPriceInCents = quantity * unitPriceInCents;
    subtotal += extendedPriceInCents;
  }

  let tierRate = 0;
  if (tier === "silver") tierRate = 500;
  if (tier === "gold") tierRate = 1000;
  const tierDiscountNumerator = 2 * subtotal * tierRate + 10000;
  const tierDiscountDenominator = 20000;
  const tierDiscount = Math.floor(tierDiscountNumerator / tierDiscountDenominator);
  const afterTier = subtotal - tierDiscount;
  const couponCalculationBase = afterTier;
  let couponDiscount = 0;
  if (coupon.startsWith("PCT")) {
    const percent = Number(coupon.slice(3));
    const percentageNumerator = 2 * afterTier * percent + 100;
    const percentageDenominator = 200;
    couponDiscount = Math.floor(percentageNumerator / percentageDenominator);
  } else if (coupon.startsWith("FIXED")) {
    const fixedAmount = Number(coupon.slice(5)) * 100;
    const fixedDiscountCannotExceedSubtotal = Math.min(fixedAmount, couponCalculationBase);
    couponDiscount = fixedDiscountCannotExceedSubtotal;
  }
  const net = couponCalculationBase - couponDiscount;

  let taxRate = 0;
  let baseShipping = 0;
  let threshold = 0;
  if (region === "EU") {
    taxRate = 2000;
    baseShipping = 800;
    threshold = 10000;
  } else if (region === "US") {
    taxRate = 700;
    baseShipping = 500;
    threshold = 7500;
  } else {
    taxRate = 1000;
    baseShipping = 1200;
    threshold = 15000;
  }
  const orderMeetsShippingThreshold = net >= threshold;
  const couponGrantsFreeShipping = coupon === "FREESHIP";
  const freeShipping = couponGrantsFreeShipping || orderMeetsShippingThreshold;
  let shipping = baseShipping;
  if (freeShipping) shipping = 0;
  const taxableAmount = net;
  const regionalTaxRate = taxRate;
  const taxNumerator = 2 * taxableAmount * regionalTaxRate + 10000;
  const taxDenominator = 20000;
  const roundedTaxAmount = taxNumerator / taxDenominator;
  const tax = Math.floor(roundedTaxAmount);
  const applied: string[] = [];
  const tierDiscountWasApplied = tierDiscount > 0;
  const couponDiscountWasApplied = couponDiscount > 0;
  const shippingWasWaived = shipping === 0;
  const taxWasCharged = tax > 0;
  if (tierDiscountWasApplied) applied.push("tier");
  if (couponDiscountWasApplied) applied.push("coupon");
  if (shippingWasWaived) applied.push("free-shipping");
  if (taxWasCharged) applied.push("tax");

  return {
    lines,
    subtotal,
    tier_discount: tierDiscount,
    coupon_discount: couponDiscount,
    shipping,
    tax,
    total: net + shipping + tax,
    applied,
  };
}
