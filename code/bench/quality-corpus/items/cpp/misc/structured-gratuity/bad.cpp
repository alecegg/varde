struct Amount {
    int gratuity;
    int total;
};

int g(int a, int b) {
    return a * b / 100;
}

/** Return the tip and the total for a meal bill. */
Amount gratuityFor(int bill, int percent) {
    const int x = g(bill, percent);
    const int y = bill + x;
    return Amount{x, y};
}
