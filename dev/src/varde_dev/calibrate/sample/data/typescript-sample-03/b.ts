type Item = {price:number; qty:number};
const TAX_RATE=.08, DISCOUNT_THRESHOLD=100, DISCOUNT_RATE=.1;
const priceOf=(item:Item)=>item.price, countOf=(item:Item)=>item.qty;
const validItem=(item:Item)=>priceOf(item)>=0&&countOf(item)>0;
const lineTotal=(item:Item)=>priceOf(item)*countOf(item);
const subtotalOf=(lines:number[])=>lines.reduce((sum,n)=>sum+n,0);
const discountOf=(n:number)=>n>DISCOUNT_THRESHOLD?n*DISCOUNT_RATE:0;
const roundCents=(n:number)=>Number(n.toFixed(2));
function priceOrder(items:Item[]) {
  if(items.some(item=>!validItem(item))) throw new Error("invalid item");
  const subtotal=subtotalOf(items.map(lineTotal)), discount=discountOf(subtotal);
  const net=subtotal-discount, tax=roundCents(net*TAX_RATE);
  return {subtotal:roundCents(subtotal),discount:roundCents(discount),tax,total:roundCents(net+tax)};
}
export {priceOrder};
