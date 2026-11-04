struct Amount {
    int gratuity;
    int total;
};

/** Return the tip and the total for a meal bill. */
Amount gratuityFor(int bill, int percent) {
    const int tip = bill * percent / 100;
    return Amount{tip, bill + tip};
}
