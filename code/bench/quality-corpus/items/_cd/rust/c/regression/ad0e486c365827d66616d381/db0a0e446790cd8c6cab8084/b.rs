// Copyright 2018 Guillaume Pinot (@TeXitoi) <texitoi@texitoi.eu>,
// Kevin Knapp (@kbknapp) <kbknapp@gmail.com>, and
// Ana Hobden (@hoverbear) <operator@hoverbear.org>
//
// Licensed under the Apache License, Version 2.0 <LICENSE-APACHE or
// http://www.apache.org/licenses/LICENSE-2.0> or the MIT license
// <LICENSE-MIT or http://opensource.org/licenses/MIT>, at your
// option. This file may not be copied, modified, or distributed
// except according to those terms.
//
// This work was derived from Structopt (https://github.com/TeXitoi/structopt)
// commit#ea76fa1b1b273e65e3b0b1046643715b49bec51f which is licensed under the
// MIT/Apache 2.0 license.



// Copyright 2018 Guillaume Pinot (@TeXitoi) <texitoi@texitoi.eu>,
// Kevin Knapp (@kbknapp) <kbknapp@gmail.com>, and
// Ana Hobden (@hoverbear) <operator@hoverbear.org>
//
// Licensed under the Apache License, Version 2.0 <LICENSE-APACHE or
// http://www.apache.org/licenses/LICENSE-2.0> or the MIT license
// <LICENSE-MIT or http://opensource.org/licenses/MIT>, at your
// option. This file may not be copied, modified, or distributed
// except according to those terms.
//
// This work was derived from Structopt (https://github.com/TeXitoi/structopt)
// commit#ea76fa1b1b273e65e3b0b1046643715b49bec51f which is licensed under the
// MIT/Apache 2.0 license.

fn optional_flatten() {
    #[derive(Parser, Debug, PartialEq, Eq)]
    struct Opt {
        #[command(flatten)]
        source: Option<Source>,
    }

    #[derive(clap::Args, Debug, PartialEq, Eq)]
    struct Source {
        crates: Vec<String>,
        #[arg(long)]
        path: Option<std::path::PathBuf>,
        #[arg(long)]
        git: Option<String>,
    }

    assert_eq!(
        Opt { source: None },
        Opt::try_parse_from(&["test"]).unwrap()
    );
    assert_eq!(
        Opt {
            source: Some(Source {
                crates: vec!["serde".to_owned()],
                path: None,
                git: None,
            }),
        },
        Opt::try_parse_from(&["test", "serde"]).unwrap()
    );
    assert_eq!(
        Opt {
            source: Some(Source {
                crates: Vec::new(),
                path: Some("./".into()),
                git: None,
            }),
        },
        Opt::try_parse_from(&["test", "--path=./"]).unwrap()
    );
}