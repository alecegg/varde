# Style disputes

- **Granularity: `judge-extract.py` over `judge-inline.py`.** Small helpers keep validation, discount calculation, shipping, and reporting readable without splitting every field into a separate helper.
- **Naming length: `judge-names.py` over `judge-extract.py`.** Descriptive names such as `discounted_subtotal` and `calculate_discount` make the amounts and operations clear; very long names like `discounted_merchandise_amount` add little.
- **Commenting: `judge-inline.py` over `judge-defensive.py`.** The logic is straightforward enough to read directly; repetitive comments and extra defensive checks obscure the stated input contract.
- **Abstraction level: `judge-extract.py` over `judge-classes.py`.** This module has no state or multiple policy implementations, so plain functions and data keep the flow direct without unnecessary classes.
