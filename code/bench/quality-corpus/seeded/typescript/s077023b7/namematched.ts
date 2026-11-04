type Plan = "basic" | "plus" | "max";
type Input = {
  customerId: string;
  period: string;
  plan: Plan;
  units: number;
  credits: number;
  taxRate: number;
};
type Invoice = {
  customerId: string;
  period: string;
  plan: Plan;
  base: number;
  includedUnits: number;
  units: number;
  overage: number;
  credits: number;
  taxable: number;
  tax: number;
  total: number;
};
type Details = { price: number; allowance: number };
const catalog: Record<Plan, Details> = {
  basic: { price: 20, allowance: 100 },
  plus: { price: 50, allowance: 500 },
  max: { price: 100, allowance: 1500 },
};
function roundCurrencyToCents(monetaryValue: number): number {
  return Math.round((monetaryValue + Number.EPSILON) * 100) / 100;
}
function isStringValue(providedInvoiceInput: unknown): boolean {
  return typeof providedInvoiceInput === "string";
}
function trimCustomerText(providedInvoiceInput: string): string {
  return providedInvoiceInput.trim();
}
function isNonblankTextValue(providedInvoiceInput: unknown): boolean {
  return (
    isStringValue(providedInvoiceInput) &&
    trimCustomerText(providedInvoiceInput).length > 0
  );
}
function isBasicPlanValue(providedInvoiceInput: unknown): boolean {
  return providedInvoiceInput === "basic";
}
function isPlusPlanValue(providedInvoiceInput: unknown): boolean {
  return providedInvoiceInput === "plus";
}
function isMaxPlanValue(providedInvoiceInput: unknown): boolean {
  return providedInvoiceInput === "max";
}
function isRecognizedPlanValue(providedInvoiceInput: unknown): boolean {
  return (
    isBasicPlanValue(providedInvoiceInput) ||
    isPlusPlanValue(providedInvoiceInput) ||
    isMaxPlanValue(providedInvoiceInput)
  );
}
function isNumberValue(providedInvoiceInput: unknown): boolean {
  return typeof providedInvoiceInput === "number";
}
function isIntegerValue(providedInvoiceInput: number): boolean {
  return Number.isInteger(providedInvoiceInput);
}
function isNonnegativeValue(providedInvoiceInput: number): boolean {
  return providedInvoiceInput >= 0;
}
function isNonnegativeIntegerValue(providedInvoiceInput: unknown): boolean {
  return (
    isNumberValue(providedInvoiceInput) &&
    isIntegerValue(providedInvoiceInput as number) &&
    isNonnegativeValue(providedInvoiceInput as number)
  );
}
function isValidCreditAmount(providedInvoiceInput: unknown): boolean {
  return (
    isNumberValue(providedInvoiceInput) &&
    Number.isFinite(providedInvoiceInput) &&
    isNonnegativeValue(providedInvoiceInput as number)
  );
}
function isFiniteRateValue(providedInvoiceInput: unknown): boolean {
  return (
    isNumberValue(providedInvoiceInput) && Number.isFinite(providedInvoiceInput)
  );
}
function isAllowedTaxRate(providedInvoiceInput: number): boolean {
  return providedInvoiceInput >= 0 && providedInvoiceInput <= 1;
}
function isValidTaxRate(providedInvoiceInput: unknown): boolean {
  return (
    isFiniteRateValue(providedInvoiceInput) &&
    isAllowedTaxRate(providedInvoiceInput as number)
  );
}
function throwInvalidFieldTypeError(fieldLabel: string): never {
  throw new TypeError(`Invalid ${fieldLabel}`);
}
function validateInvoiceCustomerIdentifier(
  providedInvoiceInput: unknown,
): asserts providedInvoiceInput is string {
  if (!isNonblankTextValue(providedInvoiceInput))
    throwInvalidFieldTypeError("customerId");
}
function validateInvoiceBillingPeriod(
  providedInvoiceInput: unknown,
): asserts providedInvoiceInput is string {
  if (!isNonblankTextValue(providedInvoiceInput))
    throwInvalidFieldTypeError("period");
}
function validateInvoicePlanSelection(
  providedInvoiceInput: unknown,
): asserts providedInvoiceInput is Plan {
  if (!isRecognizedPlanValue(providedInvoiceInput))
    throwInvalidFieldTypeError("plan");
}
function validateInvoiceUnitQuantity(
  providedInvoiceInput: unknown,
): asserts providedInvoiceInput is number {
  if (!isNonnegativeIntegerValue(providedInvoiceInput))
    throwInvalidFieldTypeError("units");
}
function validateInvoiceCreditAmount(
  providedInvoiceInput: unknown,
): asserts providedInvoiceInput is number {
  if (!isValidCreditAmount(providedInvoiceInput))
    throwInvalidFieldTypeError("credits");
}
function validateInvoiceTaxRate(
  providedInvoiceInput: unknown,
): asserts providedInvoiceInput is number {
  if (!isValidTaxRate(providedInvoiceInput))
    throwInvalidFieldTypeError("taxRate");
}
function lookupSelectedPlanDetails(p: Plan): Details {
  return catalog[p];
}
function readIncludedUnitAllowance(selectedPlanDetails: Details): number {
  return selectedPlanDetails.allowance;
}
function readBaseSubscriptionPrice(selectedPlanDetails: Details): number {
  return selectedPlanDetails.price;
}
function calculateExcessBillableUnits(
  unitQuantity: number,
  includedUnitAllowance: number,
): number {
  return Math.max(0, unitQuantity - includedUnitAllowance);
}
function calculateUsageChargeBeforeRounding(
  unitQuantity: number,
  includedUnitAllowance: number,
): number {
  return (
    calculateExcessBillableUnits(unitQuantity, includedUnitAllowance) * 0.1
  );
}
function calculateRoundedUsageCharge(
  unitQuantity: number,
  includedUnitAllowance: number,
): number {
  return roundCurrencyToCents(
    calculateUsageChargeBeforeRounding(unitQuantity, includedUnitAllowance),
  );
}
function calculateSubtotalBeforeCredits(
  b: number,
  roundedUsageCharge: number,
): number {
  return b + roundedUsageCharge;
}
function calculateAppliedCreditAmount(
  appliedCreditAmount: number,
  s: number,
): number {
  return Math.min(roundCurrencyToCents(appliedCreditAmount), s);
}
function calculateTaxableInvoiceAmount(
  s: number,
  appliedCreditAmount: number,
): number {
  return roundCurrencyToCents(s - appliedCreditAmount);
}
function calculateRoundedTaxAmount(
  providedInvoiceInput: number,
  rate: number,
): number {
  return roundCurrencyToCents(providedInvoiceInput * rate);
}
function calculateFinalInvoiceTotal(
  providedInvoiceInput: number,
  taxableInvoiceAmount: number,
): number {
  const monetaryValue = roundCurrencyToCents(
    providedInvoiceInput + taxableInvoiceAmount,
  );
  return Object.is(monetaryValue, -0) ? 0 : monetaryValue;
}
function assembleInvoiceResult(
  input: Input,
  selectedPlanDetails: Details,
  roundedUsageCharge: number,
  appliedCreditAmount: number,
  taxableInvoiceAmount: number,
  roundedTaxAmount: number,
  finalInvoiceTotal: number,
): Invoice {
  return {
    customerId: input.customerId,
    period: input.period,
    plan: input.plan,
    base: roundCurrencyToCents(readBaseSubscriptionPrice(selectedPlanDetails)),
    includedUnits: readIncludedUnitAllowance(selectedPlanDetails),
    units: input.units,
    overage: roundedUsageCharge,
    credits: appliedCreditAmount,
    taxable: taxableInvoiceAmount,
    tax: roundedTaxAmount,
    total: finalInvoiceTotal,
  };
}
export function createInvoice(input: Input): Invoice {
  const providedInvoiceInput: any = input;
  const customerId = providedInvoiceInput?.customerId;
  const period = providedInvoiceInput?.period;
  const plan = providedInvoiceInput?.plan;
  const units = providedInvoiceInput?.units;
  const credits = providedInvoiceInput?.credits;
  const taxRate = providedInvoiceInput?.taxRate;
  validateInvoiceCustomerIdentifier(customerId);
  validateInvoiceBillingPeriod(period);
  validateInvoicePlanSelection(plan);
  validateInvoiceUnitQuantity(units);
  validateInvoiceCreditAmount(credits);
  validateInvoiceTaxRate(taxRate);
  const selectedPlanDetails = lookupSelectedPlanDetails(plan);
  const roundedUsageCharge = calculateRoundedUsageCharge(
    units,
    readIncludedUnitAllowance(selectedPlanDetails),
  );
  const appliedCreditAmount = calculateAppliedCreditAmount(
    credits,
    calculateSubtotalBeforeCredits(
      readBaseSubscriptionPrice(selectedPlanDetails),
      roundedUsageCharge,
    ),
  );
  const taxableInvoiceAmount = calculateTaxableInvoiceAmount(
    calculateSubtotalBeforeCredits(
      readBaseSubscriptionPrice(selectedPlanDetails),
      roundedUsageCharge,
    ),
    appliedCreditAmount,
  );
  const roundedTaxAmount = calculateRoundedTaxAmount(
    taxableInvoiceAmount,
    taxRate,
  );
  return assembleInvoiceResult(
    { customerId, period, plan, units, credits, taxRate },
    selectedPlanDetails,
    roundedUsageCharge,
    appliedCreditAmount,
    taxableInvoiceAmount,
    roundedTaxAmount,
    calculateFinalInvoiceTotal(taxableInvoiceAmount, roundedTaxAmount),
  );
}
function formatCurrencyAmount(monetaryValue: number): string {
  return `$${monetaryValue.toFixed(2)}`;
}
function formatLabeledInvoiceLine(
  fieldLabel: string,
  providedInvoiceInput: string,
): string {
  return `${fieldLabel}: ${providedInvoiceInput}`;
}
function formatUsageDescription(invoiceRecord: Invoice): string {
  return `${invoiceRecord.units} units (${formatCurrencyAmount(invoiceRecord.overage)})`;
}
function formatCustomerInvoiceRow(invoiceRecord: Invoice): string {
  return formatLabeledInvoiceLine("Invoice", invoiceRecord.customerId);
}
function formatBillingPeriodInvoiceRow(invoiceRecord: Invoice): string {
  return formatLabeledInvoiceLine("Period", invoiceRecord.period);
}
function formatPlanInvoiceRow(invoiceRecord: Invoice): string {
  return formatLabeledInvoiceLine("Plan", invoiceRecord.plan);
}
function formatBaseInvoiceRow(invoiceRecord: Invoice): string {
  return formatLabeledInvoiceLine(
    "Base",
    formatCurrencyAmount(invoiceRecord.base),
  );
}
function formatUsageInvoiceRow(invoiceRecord: Invoice): string {
  return formatLabeledInvoiceLine(
    "Usage",
    formatUsageDescription(invoiceRecord),
  );
}
function formatCreditsInvoiceRow(invoiceRecord: Invoice): string {
  return formatLabeledInvoiceLine(
    "Credits",
    `-${formatCurrencyAmount(invoiceRecord.credits)}`,
  );
}
function formatTaxInvoiceRow(invoiceRecord: Invoice): string {
  return formatLabeledInvoiceLine(
    "Tax",
    formatCurrencyAmount(invoiceRecord.tax),
  );
}
function formatTotalInvoiceRow(invoiceRecord: Invoice): string {
  return formatLabeledInvoiceLine(
    "Total",
    formatCurrencyAmount(invoiceRecord.total),
  );
}
function assembleInvoiceReportRows(invoiceRecord: Invoice): string[] {
  return [
    formatCustomerInvoiceRow(invoiceRecord),
    formatBillingPeriodInvoiceRow(invoiceRecord),
    formatPlanInvoiceRow(invoiceRecord),
    formatBaseInvoiceRow(invoiceRecord),
    formatUsageInvoiceRow(invoiceRecord),
    formatCreditsInvoiceRow(invoiceRecord),
    formatTaxInvoiceRow(invoiceRecord),
    formatTotalInvoiceRow(invoiceRecord),
  ];
}
function joinInvoiceReportRows(reportRows: string[]): string {
  return reportRows.join("\n");
}
export function renderInvoice(invoice: Invoice): string {
  return joinInvoiceReportRows(assembleInvoiceReportRows(invoice));
}
