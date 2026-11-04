type Item = {price:number; qty:number};
const TAX_RATE=.08, DISCOUNT_THRESHOLD=100, DISCOUNT_RATE=.1;
const quantity=(item:Item)=>item.qty, unitPrice=(item:Item)=>item.price;
const quantityOk=(item:Item)=>quantity(item)>0, priceOk=(item:Item)=>unitPrice(item)>=0;
const valid=(item:Item)=>quantityOk(item)&&priceOk(item), line=(item:Item)=>unitPrice(item)*quantity(item);
const discountFor=(n:number)=>n>DISCOUNT_THRESHOLD?n*DISCOUNT_RATE:0;
const money=(n:number)=>Math.round(n*100)/100;
export function priceOrder(items:Item[]) {
  if(!items.every(valid)) throw new Error("invalid item");
  const subtotal=items.map(line).reduce((sum,n)=>sum+n,0), discount=discountFor(subtotal);
  const taxable=subtotal-discount, tax=money(taxable*TAX_RATE);
  return {subtotal:money(subtotal),discount:money(discount),tax,total:money(taxable+tax)};
}
