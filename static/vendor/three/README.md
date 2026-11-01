# Three.js 0.187.0

Source: https://registry.npmjs.org/three/-/three-0.187.0.tgz
License: MIT (LICENSE included).

Vendored build/three.module.js and build/three.core.js, plus
examples/jsm/utils/BufferGeometryUtils.js. The utility's bare `three` import
is changed to `./three.module.js` for self hosting without an import map.
No other upstream code changes. Used only by the lazy loaded lab scene.
