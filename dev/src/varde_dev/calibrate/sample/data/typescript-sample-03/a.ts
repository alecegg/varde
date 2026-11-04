type Item = {price:number; qty:number};
const TAX_RATE=.08, DISCOUNT_THRESHOLD=100, DISCOUNT_RATE=.1;
export function priceOrder(items:Item[]) {
  let subtotal=0;
  for(const item of items) {
    if(item.price<0||item.qty<=0) throw new Error("invalid item");
    subtotal+=item.price*item.qty;
  }
  const discount=subtotal>DISCOUNT_THRESHOLD?subtotal/10:0, taxable=subtotal-discount;
  const tax=Math.round(taxable*TAX_RATE*100)/100;
  return {subtotal:Math.round(subtotal*100)/100,discount:Math.round(discount*100)/100,tax,total:Math.round((taxable+tax)*100)/100};
}
