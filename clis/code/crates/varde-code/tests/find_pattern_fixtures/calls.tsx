function alpha(x: number): void {}
function beta(x: number): void {}
const receiver = { name(x: number) {} };
alpha(1);
alpha(2, 3);
receiver.name(4);
beta(5);
