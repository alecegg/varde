#[derive(Debug, Clone, PartialEq)]
pub struct Request {
    pub property_id: String,
    pub arrival: i64,
    pub departure: i64,
    pub adults: i64,
    pub children: i64,
    pub extras: Vec<String>,
    pub bookings: Vec<Booking>,
    pub promo_code: String,
}
#[derive(Debug, Clone, PartialEq)]
pub struct Booking {
    pub property_id: String,
    pub arrival: i64,
    pub departure: i64,
}
#[derive(Debug, Clone, PartialEq)]
pub struct NightLine {
    pub day: i64,
    pub season: String,
    pub base_cents: i64,
    pub weekend_cents: i64,
    pub night_cents: i64,
}
#[derive(Debug, Clone, PartialEq)]
pub struct Quote {
    pub nights: i64,
    pub night_lines: Vec<NightLine>,
    pub cleaning_fee: i64,
    pub extra_guest_fee: i64,
    pub tourist_tax: i64,
    pub extras_fee: i64,
    pub long_stay_discount: i64,
    pub promo_discount: i64,
    pub total: i64,
    pub deposit: i64,
    pub balance_due: i64,
    pub applied: Vec<String>,
    pub cancellation: String,
}
#[derive(Debug, Clone, PartialEq)]
pub enum Outcome {
    Quote(Quote),
    Error { code: String, index: Option<usize> },
}
const CLEANING_FEE: i64 = 4500;
const DAYS: std::ops::RangeInclusive<i64> = 0..=1_000_000;
const PROPERTIES: [&str; 2] = ["CEDAR", "LAKE"];
const PROMOS: [&str; 4] = ["", "PCT10", "FIXED5000", "ONENIGHT"];

struct RentalQuote<'a> {
    request: &'a Request,
    property: String,
    promo: String,
    extras: Vec<String>,
    bookings: Vec<Booking>,
    nights: i64,
    subtotal: i64,
    lines: Vec<NightLine>,
    guests: i64,
    tax: i64,
    extra_fees: i64,
    long: i64,
    promo_cut: i64,
    total: i64,
}

fn reject(code: &str, index: Option<usize>) -> Outcome {
    Outcome::Error {
        code: code.into(),
        index,
    }
}

fn season(day: i64) -> (&'static str, i64, i64) {
    match day.rem_euclid(365) {
        0..=119 => ("LOW", 5000, 1),
        120..=239 => ("PEAK", 9000, 3),
        _ => ("SHOULDER", 6500, 2),
    }
}

impl<'a> RentalQuote<'a> {
    fn normalised_bookings(request: &Request) -> Vec<Booking> {
        let bookings = request.bookings.iter();
        bookings
            .map(|b| Booking {
                property_id: b.property_id.trim_matches(' ').to_ascii_uppercase(),
                ..b.clone()
            })
            .collect()
    }

    fn new(request: &'a Request) -> Self {
        Self {
            request,
            property: request.property_id.trim_matches(' ').to_ascii_uppercase(),
            promo: request.promo_code.trim_matches(' ').to_ascii_uppercase(),
            extras: request
                .extras
                .iter()
                .map(|e| e.trim_matches(' ').to_ascii_uppercase())
                .collect(),
            bookings: Self::normalised_bookings(request),
            nights: 0,
            subtotal: 0,
            lines: Vec::new(),
            guests: 0,
            tax: 0,
            extra_fees: 0,
            long: 0,
            promo_cut: 0,
            total: 0,
        }
    }

    fn check_identity(&self) -> Result<(), Outcome> {
        let request = self.request;
        if !PROPERTIES.contains(&self.property.as_str()) {
            return Err(reject("BAD_PROPERTY", None));
        }
        if !(1..=8).contains(&request.adults) {
            return Err(reject("BAD_ADULTS", None));
        }
        if !(0..=8).contains(&request.children) {
            return Err(reject("BAD_CHILDREN", None));
        }
        Ok(())
    }

    fn check_dates(&mut self) -> Result<(), Outcome> {
        let request = self.request;
        let bounded = [request.arrival, request.departure]
            .iter()
            .all(|day| DAYS.contains(day));
        if !bounded || request.departure <= request.arrival {
            return Err(reject("BAD_DAYS", None));
        }
        self.nights = request.departure - request.arrival;
        Ok(())
    }

    fn check_extras(&self) -> Result<(), Outcome> {
        if self.extras.len() > 4 {
            return Err(reject("BAD_EXTRA", None));
        }
        for (index, extra) in self.extras.iter().enumerate() {
            let known = extra == "PET" || extra == "PARKING";
            if !known || self.extras[..index].contains(extra) {
                return Err(reject("BAD_EXTRA", Some(index)));
            }
        }
        Ok(())
    }

    fn check_bookings(&self) -> Result<(), Outcome> {
        if self.bookings.len() > 100 {
            return Err(reject("BAD_BOOKING", None));
        }
        let broken = self.bookings.iter().position(|b| {
            let known = PROPERTIES.contains(&b.property_id.as_str());
            let bounded = DAYS.contains(&b.arrival) && DAYS.contains(&b.departure);
            !(known && bounded && b.departure > b.arrival)
        });
        match broken {
            Some(index) => Err(reject("BAD_BOOKING", Some(index))),
            None => Ok(()),
        }
    }

    fn check_stay(&self) -> Result<(), Outcome> {
        let request = self.request;
        if !(1..=30).contains(&self.nights) {
            return Err(reject("BAD_STAY", None));
        }
        let capacity = if self.property == "CEDAR" { 4 } else { 6 };
        if request.adults + request.children > capacity {
            return Err(reject("OVER_CAPACITY", None));
        }
        if (request.arrival..request.departure).any(|day| season(day).2 > self.nights) {
            return Err(reject("MIN_STAY", None));
        }
        Ok(())
    }

    fn check_availability(&self) -> Result<(), Outcome> {
        let request = self.request;
        let clash = self.bookings.iter().position(|b| {
            b.property_id == self.property
                && request.arrival < b.departure
                && b.arrival < request.departure
        });
        match clash {
            Some(index) => Err(reject("UNAVAILABLE", Some(index))),
            None => Ok(()),
        }
    }

    fn validate(&mut self) -> Result<(), Outcome> {
        self.check_identity()?;
        self.check_dates()?;
        self.check_extras()?;
        self.check_bookings()?;
        self.check_stay()?;
        self.check_availability()?;
        if !PROMOS.contains(&self.promo.as_str()) {
            return Err(reject("BAD_PROMO", None));
        }
        Ok(())
    }

    fn build_lines(&mut self) {
        let request = self.request;
        self.lines = (request.arrival..request.departure)
            .map(|day| {
                let (name, base, _) = season(day);
                let weekend = if matches!(day.rem_euclid(7), 4 | 5) {
                    1500
                } else {
                    0
                };
                NightLine {
                    day,
                    season: name.into(),
                    base_cents: base,
                    weekend_cents: weekend,
                    night_cents: base + weekend,
                }
            })
            .collect();
        self.subtotal = self.lines.iter().map(|line| line.night_cents).sum();
    }

    fn set_fees(&mut self) {
        let request = self.request;
        let nights = self.nights;
        self.guests = (2000 * (request.adults - 2).max(0) + 1000 * request.children) * nights;
        self.tax = 800 * (request.adults + request.children) * nights.min(5);
        self.extra_fees = self
            .extras
            .iter()
            .map(|extra| {
                if extra == "PARKING" {
                    1200 * nights
                } else {
                    2500
                }
            })
            .sum();
    }

    fn set_long(&mut self) {
        let rate = match self.nights {
            14.. => 15,
            7.. => 10,
            _ => 0,
        };
        self.long = (2 * self.subtotal * rate + 100) / 200;
    }

    fn set_discounts(&mut self) {
        self.set_long();
        let fees = CLEANING_FEE + self.guests + self.tax + self.extra_fees;
        let remaining = self.subtotal + fees - self.long;
        self.promo_cut = match self.promo.as_str() {
            "PCT10" => (2 * remaining * 10 + 100) / 200,
            "FIXED5000" => remaining.min(5000),
            "ONENIGHT" => self
                .lines
                .iter()
                .map(|l| l.night_cents)
                .fold(i64::MAX, i64::min),
            _ => 0,
        };
        self.total = remaining - self.promo_cut;
    }

    fn required_deposit(&self) -> i64 {
        self.total
            .min(10_000.max((2 * self.total * 30 + 100) / 200))
    }

    fn fee_labels(&self) -> Vec<String> {
        [
            (
                self.lines.iter().any(|line| line.weekend_cents > 0),
                "weekend",
            ),
            (true, "cleaning"),
            (self.guests > 0, "extra-guests"),
            (self.tax > 0, "tourist-tax"),
        ]
        .into_iter()
        .filter(|(on, _)| *on)
        .map(|(_, name)| name.to_string())
        .collect()
    }

    fn adjustment_labels(&self) -> Vec<String> {
        [
            (self.extras.iter().any(|e| e == "PARKING"), "parking"),
            (self.extras.iter().any(|e| e == "PET"), "pet"),
            (self.long > 0, "long-stay"),
            (self.promo_cut > 0, "promo"),
            (self.total > 0, "deposit"),
        ]
        .into_iter()
        .filter(|(on, _)| *on)
        .map(|(_, name)| name.to_string())
        .collect()
    }

    fn finish(self) -> Outcome {
        let applied = [self.fee_labels(), self.adjustment_labels()].concat();
        let deposit = self.required_deposit();
        Outcome::Quote(Quote {
            nights: self.nights,
            night_lines: self.lines,
            cleaning_fee: CLEANING_FEE,
            extra_guest_fee: self.guests,
            tourist_tax: self.tax,
            extras_fee: self.extra_fees,
            long_stay_discount: self.long,
            promo_discount: self.promo_cut,
            total: self.total,
            deposit,
            balance_due: self.total - deposit,
            applied,
            cancellation: match self.request.arrival {
                30.. => "FLEX",
                7.. => "STANDARD",
                _ => "FIRM",
            }
            .into(),
        })
    }
}

/// Compute a rental quote with a struct that owns validation, pricing, and labels.
pub fn solution(request: &Request) -> Outcome {
    let mut quote = RentalQuote::new(request);
    if let Err(outcome) = quote.validate() {
        return outcome;
    }
    quote.build_lines();
    quote.set_fees();
    quote.set_discounts();
    quote.finish()
}
