void alpha(Object a, [Object? b]) {}
void beta(Object a) {}
void main() {
  alpha(1);
  alpha(1, 2);
  objectRef.alpha(3);
  beta(4);
}
