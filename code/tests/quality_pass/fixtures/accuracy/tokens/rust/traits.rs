pub trait Render {
    fn render(&self) -> String;

    fn label(&self) -> &'static str {
        "item"
    }
}

pub struct Panel {
    pub title: String,
    pub items: Vec<String>,
}

impl Render for Panel {
    fn render(&self) -> String {
        let mut parts = vec![self.title.clone()];
        for item in &self.items {
            parts.push(item.to_uppercase());
        }
        parts.join(", ")
    }
}

pub fn render_all<'a, I>(view: I) -> Vec<String>
where
    I: IntoIterator<Item = &'a Panel>,
{
    view.into_iter().map(Render::render).collect()
}
