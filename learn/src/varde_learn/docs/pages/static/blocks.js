// First-party enhancement of the typed visual blocks. Reads only the DOM it is
// given, builds nodes with createElement/textContent, does no network. Every
// block works without this script; each widget is added on top of the markup.
// The widgets live in ES modules by kind (table, tabs, flow, chart, diagram, wireframe, code, annotated, er, sequence, image, screen-flow; viewport is
// shared pan and zoom); this classic script loads them and wires `enhance`.
(() => {
  'use strict';
  const page = document.querySelector('main[data-role="page"]');
  if (!page) return;
  const parts = ['./table.js', './tabs.js', './flow.js', './chart.js', './diagram.js', './wireframe.js', './code.js', './annotated.js', './er.js', './containers.js', './sequence.js', './image.js', './screen_flow.js'];
  Promise.all(parts.map((part) => import(part))).then(([table, tabs, flow, chart, diagram, wireframe, code, annotated, er, containers, sequence, image, screenFlow]) => {
    function enhance(scope) {
      for (const block of scope.querySelectorAll('.vb:not([data-vb-ready])')) {
        block.dataset.vbReady = '1';
        table.enhanceTables(block);
        tabs.enhanceStates(block);
        flow.enhanceFlow(block);
        chart.enhanceChart(block);
        diagram.enhanceDiagram(block);
        wireframe.enhanceWireframe(block);
        code.enhanceCode(block);
        annotated.enhanceAnnotated(block);
        er.enhanceEr(block);
        containers.enhanceContainers(block);
        sequence.enhanceSequence(block);
        image.enhanceImage(block);
        screenFlow.enhanceScreenFlow(block);
      }
    }
    enhance(page);
    // app.js swaps the page children on every live update; enhance the new nodes.
    new MutationObserver(() => enhance(page)).observe(page, { childList: true });
  });
})();
