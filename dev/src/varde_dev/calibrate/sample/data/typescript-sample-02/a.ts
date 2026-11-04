type Item = {price:number; qty:number};
const TAX_RATE=.08, DISCOUNT_THRESHOLD=100, DISCOUNT_RATE=.1;
const cents=(n:number)=>Math.round(n*100)/100;
export function priceOrder(items:Item[]) {
  const rows=Array.from(items);
  if(rows.some(({price,qty})=>price<0||qty<1)) throw new Error("invalid item");
  const subtotal=rows.reduce((sum,item)=>sum+item.price*item.qty,0);
  const discount=subtotal>DISCOUNT_THRESHOLD?subtotal*DISCOUNT_RATE:0;
  const taxable=subtotal-discount, tax=cents(taxable*TAX_RATE);
  return {subtotal:cents(subtotal),discount:cents(discount),tax,total:cents(taxable+tax)};
}
