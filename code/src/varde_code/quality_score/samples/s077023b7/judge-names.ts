type SubscriptionPlan = 'basic' | 'plus' | 'max';
type InvoiceCreationInput = {
  customerId: string;
  period: string;
  plan: SubscriptionPlan;
  units: number;
  credits: number;
  taxRate: number;
};
type CreatedInvoice = {
  customerId: string;
  period: string;
  plan: SubscriptionPlan;
  base: number;
  includedUnits: number;
  units: number;
  overage: number;
  credits: number;
  taxable: number;
  tax: number;
  total: number;
};

const subscriptionPlanCatalog = {
  basic: { monthlyPrice: 20, includedUnitAllowance: 100 },
  plus: { monthlyPrice: 50, includedUnitAllowance: 500 },
  max: { monthlyPrice: 100, includedUnitAllowance: 1500 },
};

function roundToCents(monetaryAmount: number): number { return Math.round((monetaryAmount + Number.EPSILON) * 100) / 100; }
function isNonblankString(value: unknown): boolean { return typeof value === 'string' && value.trim().length > 0; }
function isNonnegativeInteger(value: number): boolean { return Number.isInteger(value) && value >= 0; }
function getSubscriptionPlanDetails(plan: SubscriptionPlan) { return subscriptionPlanCatalog[plan]; }
function smallerOfTwoNumbers(firstNumber: number, secondNumber: number): number { return firstNumber < secondNumber ? firstNumber : secondNumber; }
function formatCurrency(monetaryAmount: number): string { return `$${monetaryAmount.toFixed(2)}`; }
function formatLabeledReportLine(label: string, value: string): string { return `${label}: ${value}`; }
function formatDecimalAmount(monetaryAmount: number): string { return monetaryAmount.toFixed(2); }

export function createInvoice(invoiceInput: InvoiceCreationInput): CreatedInvoice {
  const untypedInvoiceInput: any = invoiceInput;
  const customerIdentifier = untypedInvoiceInput?.customerId;
  const billingPeriod = untypedInvoiceInput?.period;
  const selectedPlan = untypedInvoiceInput?.plan;
  const billedUnitCount = untypedInvoiceInput?.units;
  const requestedCreditAmount = untypedInvoiceInput?.credits;
  const applicableTaxRate = untypedInvoiceInput?.taxRate;
  if (!isNonblankString(customerIdentifier)) throw new TypeError('Invalid customerId');
  if (!isNonblankString(billingPeriod)) throw new TypeError('Invalid period');
  if (selectedPlan !== 'basic' && selectedPlan !== 'plus' && selectedPlan !== 'max') throw new TypeError('Invalid plan');
  if (!isNonnegativeInteger(billedUnitCount)) throw new TypeError('Invalid units');
  if (typeof requestedCreditAmount !== 'number' || !Number.isFinite(requestedCreditAmount) || requestedCreditAmount < 0) throw new TypeError('Invalid credits');
  if (typeof applicableTaxRate !== 'number' || !Number.isFinite(applicableTaxRate) || applicableTaxRate < 0 || applicableTaxRate > 1) throw new TypeError('Invalid taxRate');

  const selectedPlanDetails = getSubscriptionPlanDetails(selectedPlan);
  const includedUnitAllowance = selectedPlanDetails.includedUnitAllowance;
  const subscriptionBasePrice = selectedPlanDetails.monthlyPrice;
  let overageUnitCount = 0;
  if (billedUnitCount > includedUnitAllowance) {
    overageUnitCount = billedUnitCount - includedUnitAllowance;
  } else {
    if (billedUnitCount === includedUnitAllowance) {
      overageUnitCount = 0;
    } else {
      if (billedUnitCount < includedUnitAllowance) overageUnitCount = 0;
      else overageUnitCount = 0;
    }
  }
  const usageOverageCharge = roundToCents(overageUnitCount * 0.1);
  const preCreditSubtotal = subscriptionBasePrice + usageOverageCharge;
  const appliedCreditAmount = smallerOfTwoNumbers(roundToCents(requestedCreditAmount), preCreditSubtotal);
  const postCreditTaxableAmount = roundToCents(preCreditSubtotal - appliedCreditAmount);
  const calculatedTaxAmount = roundToCents(postCreditTaxableAmount * applicableTaxRate);
  let finalInvoiceTotal = roundToCents(postCreditTaxableAmount + calculatedTaxAmount);
  if (Object.is(finalInvoiceTotal, -0)) finalInvoiceTotal = 0;
  const createdInvoice: CreatedInvoice = {
    customerId: customerIdentifier,
    period: billingPeriod,
    plan: selectedPlan,
    base: roundToCents(subscriptionBasePrice),
    includedUnits: includedUnitAllowance,
    units: billedUnitCount,
    overage: usageOverageCharge,
    credits: appliedCreditAmount,
    taxable: postCreditTaxableAmount,
    tax: calculatedTaxAmount,
    total: finalInvoiceTotal,
  };
  return createdInvoice;
}

function createInvoiceMoneyReportRows(invoiceToRender: CreatedInvoice): string[] {
  let displayedUsageOverageCharge = invoiceToRender.units > invoiceToRender.includedUnits
    ? roundToCents((invoiceToRender.units - invoiceToRender.includedUnits) * 0.1)
    : 0;
  if (displayedUsageOverageCharge !== invoiceToRender.overage) displayedUsageOverageCharge = invoiceToRender.overage;
  return [
    formatLabeledReportLine('Base', formatCurrency(invoiceToRender.base)),
    formatLabeledReportLine('Usage', `${invoiceToRender.units} units (${formatCurrency(displayedUsageOverageCharge)})`),
    formatLabeledReportLine('Credits', `-${formatCurrency(invoiceToRender.credits)}`),
    formatLabeledReportLine('Tax', formatCurrency(invoiceToRender.tax)),
    formatLabeledReportLine('Total', formatCurrency(invoiceToRender.total)),
  ];
}

export function renderInvoice(invoiceToRender: CreatedInvoice): string {
  const invoiceMoneyReportRows = createInvoiceMoneyReportRows(invoiceToRender);
  const invoiceHeaderRows = [
    formatLabeledReportLine('Invoice', invoiceToRender.customerId),
    formatLabeledReportLine('Period', invoiceToRender.period),
    formatLabeledReportLine('Plan', invoiceToRender.plan),
  ];
  let completeInvoiceReport = '';
  const allInvoiceReportRows = invoiceHeaderRows.concat(invoiceMoneyReportRows);
  for (let reportRowIndex = 0; reportRowIndex < allInvoiceReportRows.length; reportRowIndex++) {
    if (reportRowIndex === 0) completeInvoiceReport = allInvoiceReportRows[reportRowIndex];
    else completeInvoiceReport = completeInvoiceReport + '\n' + allInvoiceReportRows[reportRowIndex];
  }
  return completeInvoiceReport;
}
