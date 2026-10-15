// 3D-тыква для резьбы (/carve) и аллеи (/tv, позже): модель, материалы с масками, свеча, резчик.
//
// Состояние тыквы = маска развёртки RGBA: R = «насквозь» (through), G = глубина декора (depth).
// Резка идёт проходом в UV-пространстве: каждый тексель тела проецируется камерой, при которой
// сделан разрез, и вырезается, только если он попал в контур, смотрит на камеру и не закрыт
// другими частями (сравнение с буфером глубины). Поэтому задняя стенка не страдает, а разрез
// одинаково ложится на все острова развёртки (швы модели не мешают).
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

export const MASK_SIZE = 2048;
const WALL = 0.06;            // толщина стенки (радиус тела = 1)
const SHAPE_RES = 1024;       // разрешение экранной маски разреза
const DILATE = 2;             // сколько текселей добивать за края островов развёртки
const FLESH = new THREE.Color(0xf6b24e);
const WARM = new THREE.Color(0xff9a3c);

// ---------------------------------------------------------------- модель

export async function loadModel(url = '/assets/carve/pumpkin.glb') {
  try {
    const gltf = await new GLTFLoader().loadAsync(url);
    return fromGltf(gltf);
  } catch (e) {
    console.warn('Модель тыквы не загрузилась, беру процедурную', e);
    return proceduralModel();
  }
}

function fromGltf(gltf) {
  gltf.scene.updateMatrixWorld(true);
  const parts = [];
  gltf.scene.traverse((o) => {
    if (!o.isMesh) return;
    const g = o.geometry.clone().applyMatrix4(o.matrixWorld);
    g.computeBoundingBox();
    const s = g.boundingBox.getSize(new THREE.Vector3());
    parts.push({ geometry: g, material: o.material, volume: s.x * s.y * s.z });
  });
  if (!parts.length) throw new Error('в модели нет мешей');
  parts.sort((a, b) => b.volume - a.volume);
  const body = parts[0];
  for (const p of parts) if (!p.geometry.attributes.normal) p.geometry.computeVertexNormals();
  normalize(parts.map((p) => p.geometry), body.geometry);
  const stems = parts.slice(1).map((p) => p.geometry);
  return {
    body: body.geometry,
    stem: stems.length ? mergeSimple(stems) : null,
    bodyMaterial: body.material,
    stemMaterial: parts[1]?.material || body.material,
    procedural: false,
  };
}

// Центр тела в начале координат, радиус тела по горизонтали = 1.
function normalize(geoms, body) {
  body.computeBoundingBox();
  const bb = body.boundingBox;
  const c = bb.getCenter(new THREE.Vector3());
  const k = 1 / Math.max(bb.max.x - bb.min.x, bb.max.z - bb.min.z) * 2;
  const m = new THREE.Matrix4().makeScale(k, k, k).multiply(new THREE.Matrix4().makeTranslation(-c.x, -c.y, -c.z));
  for (const g of geoms) { g.applyMatrix4(m); g.computeBoundingBox(); g.computeBoundingSphere(); }
}

function mergeSimple(list) {
  if (list.length === 1) return list[0];
  // черенок из нескольких частей: склеиваем только позиции/нормали/uv
  const out = new THREE.BufferGeometry();
  for (const name of ['position', 'normal', 'uv']) {
    const arrs = list.map((g) => g.toNonIndexed().attributes[name]).filter(Boolean);
    if (arrs.length !== list.length) continue;
    const size = arrs[0].itemSize;
    const data = new Float32Array(arrs.reduce((n, a) => n + a.array.length, 0));
    let off = 0;
    for (const a of arrs) { data.set(a.array, off); off += a.array.length; }
    out.setAttribute(name, new THREE.BufferAttribute(data, size));
  }
  return out;
}

// Запасная процедурная тыква (если нет assets/carve/pumpkin.glb).
function proceduralModel() {
  const body = new THREE.SphereGeometry(1, 128, 72);
  const p = body.attributes.position;
  const v = new THREE.Vector3();
  for (let i = 0; i < p.count; i++) {
    v.fromBufferAttribute(p, i);
    const th = Math.atan2(v.z, v.x);
    const rib = 1 - 0.07 * Math.pow(Math.abs(Math.cos(5 * th)), 6);
    const rxz = Math.hypot(v.x, v.z);
    let y = v.y * 0.78;
    y -= 0.18 * Math.exp(-(rxz * rxz) / 0.06) * Math.sign(v.y);
    p.setXYZ(i, v.x * rib, y, v.z * rib);
  }
  body.computeVertexNormals();
  const stem = new THREE.CylinderGeometry(0.07, 0.11, 0.35, 16);
  stem.translate(0, 0.72, 0);
  return {
    body,
    stem,
    bodyMaterial: new THREE.MeshStandardMaterial({ color: 0xe8761a, roughness: 0.55 }),
    stemMaterial: new THREE.MeshStandardMaterial({ color: 0x5b6b2a, roughness: 0.8 }),
    procedural: true,
  };
}

// Внутренняя оболочка: тело, сдвинутое внутрь по усреднённым нормалям (одинаково по обе стороны шва).
function innerShell(body) {
  const g = body.clone();
  const pos = g.attributes.position;
  const nrm = g.attributes.normal;
  const sums = new Map();
  const key = (i) => `${pos.getX(i).toFixed(4)},${pos.getY(i).toFixed(4)},${pos.getZ(i).toFixed(4)}`;
  for (let i = 0; i < pos.count; i++) {
    const k = key(i);
    const s = sums.get(k) || [0, 0, 0];
    s[0] += nrm.getX(i); s[1] += nrm.getY(i); s[2] += nrm.getZ(i);
    sums.set(k, s);
  }
  const out = new Float32Array(pos.count * 3);
  for (let i = 0; i < pos.count; i++) {
    const s = sums.get(key(i));
    const n = new THREE.Vector3(s[0], s[1], s[2]).normalize();
    out[i * 3] = pos.getX(i) - n.x * WALL;
    out[i * 3 + 1] = pos.getY(i) - n.y * WALL;
    out[i * 3 + 2] = pos.getZ(i) - n.z * WALL;
  }
  g.setAttribute('position', new THREE.BufferAttribute(out, 3));
  g.deleteAttribute('tangent');
  g.computeBoundingBox();
  g.computeBoundingSphere();
  return g;
}

// Высота дна ямки черенка: всё, что ниже, у черенка скрываем (он торчит внутрь тела).
function stemCutY(body) {
  const p = body.attributes.position;
  let best = Infinity;
  for (let i = 0; i < p.count; i++) {
    const y = p.getY(i);
    if (y > 0 && Math.hypot(p.getX(i), p.getZ(i)) < 0.12) best = Math.min(best, y);
  }
  return Number.isFinite(best) ? best - 0.03 : -Infinity;
}

// ---------------------------------------------------------------- материалы с маской

function patchMasked(material, uniforms, { decor = false, innerGlow = false, cutBelowY = null } = {}) {
  material.onBeforeCompile = (sh) => {
    Object.assign(sh.uniforms, uniforms);
    sh.vertexShader = 'varying vec2 vCarveUv;\nvarying vec3 vCarvePos;\n' + sh.vertexShader.replace(
      '#include <uv_vertex>', '#include <uv_vertex>\nvCarveUv = uv;\nvCarvePos = position;');
    let f = 'uniform sampler2D carveMask;\nuniform vec3 carveFlesh;\nuniform vec3 carveGlow;\nuniform vec3 carveInnerGlow;\n'
      + 'uniform vec3 carveCandle;\nvarying vec2 vCarveUv;\nvarying vec3 vCarvePos;\n' + sh.fragmentShader;
    let head = '#include <clipping_planes_fragment>\n';
    if (cutBelowY !== null) head += `if (vCarvePos.y < ${cutBelowY.toFixed(4)}) discard;\n`;
    else head += 'vec4 carveM = texture2D(carveMask, vCarveUv);\nif (carveM.r > 0.5) discard;\n';
    f = f.replace('#include <clipping_planes_fragment>', head);
    if (decor) {
      f = f.replace('#include <map_fragment>', '#include <map_fragment>\ndiffuseColor.rgb = mix(diffuseColor.rgb, carveFlesh, carveM.g * 0.85);');
      f = f.replace('#include <emissivemap_fragment>', '#include <emissivemap_fragment>\ntotalEmissiveRadiance += carveGlow * carveM.g;');
    }
    if (innerGlow) {
      // свеча светит изнутри: ярче рядом с пламенем, обращённая внутрь сторона ярче стенки разреза
      f = f.replace('#include <emissivemap_fragment>', `#include <emissivemap_fragment>
        float carveD = distance(vCarvePos, carveCandle);
        totalEmissiveRadiance += carveInnerGlow * (0.35 + 1.4 * exp(-carveD * carveD * 1.6)) * (gl_FrontFacing ? 0.45 : 1.0);`);
    }
    sh.fragmentShader = f;
  };
  material.customProgramCacheKey = () => `carve-${decor}-${innerGlow}-${cutBelowY}`;
  return material;
}

// ---------------------------------------------------------------- сцена тыквы

export class PumpkinStage {
  constructor(model) {
    this.model = model;
    this.scene = new THREE.Scene();
    this.uniforms = {
      carveMask: { value: null },
      carveFlesh: { value: FLESH.clone() },
      carveGlow: { value: new THREE.Color(0, 0, 0) },
      carveInnerGlow: { value: new THREE.Color(0, 0, 0) },
      carveCandle: { value: new THREE.Vector3() },
    };
    this.group = new THREE.Group();
    this.scene.add(this.group);

    const outerMat = model.bodyMaterial.clone();
    outerMat.side = THREE.FrontSide;
    this.outer = new THREE.Mesh(model.body, patchMasked(outerMat, this.uniforms, { decor: true }));
    this.innerGeometry = innerShell(model.body);
    const innerMat = new THREE.MeshStandardMaterial({ color: FLESH, roughness: 0.85, side: THREE.DoubleSide });
    this.inner = new THREE.Mesh(this.innerGeometry, patchMasked(innerMat, this.uniforms, { innerGlow: true }));
    this.group.add(this.outer, this.inner);
    this.stemCut = stemCutY(model.body);
    if (model.stem) {
      const stemMat = model.stemMaterial.clone();
      this.stem = new THREE.Mesh(model.stem, patchMasked(stemMat, this.uniforms, { cutBelowY: this.stemCut }));
      this.group.add(this.stem);
    }

    // свеча внутри
    model.body.computeBoundingBox();
    const floor = model.body.boundingBox.min.y + WALL + 0.05;
    const candle = new THREE.Group();
    this.waxMat = new THREE.MeshStandardMaterial({ color: 0xf3e6cf, roughness: 0.6 });
    const wax = new THREE.Mesh(new THREE.CylinderGeometry(0.11, 0.12, 0.22, 20), this.waxMat);
    wax.position.y = floor + 0.11;
    this.flame = new THREE.Mesh(new THREE.SphereGeometry(0.045, 12, 10), new THREE.MeshBasicMaterial({ color: 0xffd27a }));
    this.flame.scale.set(1, 1.9, 1);
    this.flame.position.y = floor + 0.3;
    candle.add(wax, this.flame);
    this.group.add(candle);
    // Точечного света нет: без теней он светил бы сквозь стенку. Свеча = свечение изнутри (шейдер).
    this.uniforms.carveCandle.value.set(0, floor + 0.3, 0);

    // свет комнаты
    this.hemi = new THREE.HemisphereLight(0xfff1e0, 0x2a1d14, 1.4);
    this.sun = new THREE.DirectionalLight(0xffffff, 2.2);
    this.sun.position.set(2, 4, 5);
    this.scene.add(this.hemi, this.sun);

    this.dark = false;
    this.flicker = 1;
    this.setDark(false);
  }

  setMask(texture) { this.uniforms.carveMask.value = texture; }

  setDark(dark) {
    this.dark = dark;
    this.scene.background = new THREE.Color(dark ? 0x050302 : 0x2b221c);
    this.hemi.intensity = dark ? 0.04 : 1.4;
    this.sun.intensity = dark ? 0 : 2.2;
    this.flame.visible = dark;
    this.applyCandle();
  }

  applyCandle() {
    const level = this.dark ? this.flicker : 0;
    this.uniforms.carveGlow.value.copy(WARM).multiplyScalar(0.9 * level);
    this.uniforms.carveInnerGlow.value.copy(WARM).multiplyScalar(1.5 * level);
    this.waxMat.emissive.copy(WARM).multiplyScalar(0.45 * level);
  }

  // Мерцание свечи; t в секундах. Возвращает true, если нужно перерисовать.
  tick(t) {
    if (!this.dark) return false;
    this.flicker = 0.86 + 0.07 * Math.sin(t * 7.3) + 0.05 * Math.sin(t * 13.1 + 1.7) + 0.03 * Math.sin(t * 23.9);
    this.flame.scale.set(1, 1.8 + 0.25 * Math.sin(t * 11), 1);
    this.applyCandle();
    return true;
  }
}

// ---------------------------------------------------------------- орбитальная камера

export function orbitCamera(cam, aspect, camera = new THREE.PerspectiveCamera(35, aspect, 0.1, 50)) {
  const { theta, phi, radius } = cam;
  camera.aspect = aspect;
  camera.position.set(radius * Math.sin(phi) * Math.sin(theta), radius * Math.cos(phi), radius * Math.sin(phi) * Math.cos(theta));
  camera.lookAt(0, 0, 0);
  camera.updateProjectionMatrix();
  camera.updateMatrixWorld();
  return camera;
}

export const DEFAULT_CAM = { theta: 0, phi: 1.3, radius: 4.6 };

// ---------------------------------------------------------------- проходы на весь экран

const QUAD_VS = 'varying vec2 vUv;\nvoid main(){ vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }';

class Quad {
  constructor(fragmentShader, uniforms) {
    this.material = new THREE.ShaderMaterial({ vertexShader: QUAD_VS, fragmentShader, uniforms, depthTest: false, depthWrite: false, blending: THREE.NoBlending });
    this.mesh = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), this.material);
    this.mesh.frustumCulled = false;
    this.scene = new THREE.Scene();
    this.scene.add(this.mesh);
    this.camera = new THREE.Camera();
  }
  render(renderer, target) {
    renderer.setRenderTarget(target);
    renderer.render(this.scene, this.camera);
  }
}

function maskTarget(size) {
  return new THREE.WebGLRenderTarget(size, size, {
    minFilter: THREE.LinearFilter, magFilter: THREE.LinearFilter,
    generateMipmaps: false, depthBuffer: false, type: THREE.UnsignedByteType,
  });
}

// ---------------------------------------------------------------- резчик

export class Carver {
  constructor(renderer, stage, size = MASK_SIZE) {
    this.renderer = renderer;
    this.stage = stage;
    this.size = size;
    this.maxUndo = 20;
    this.ops = [];
    this.base = maskTarget(size);      // состояние до первого отменяемого шага
    this.mask = maskTarget(size);      // накопленная маска
    this.display = maskTarget(size);   // маска с добивкой за края островов (для показа)
    this.coverage = maskTarget(size);  // где в развёртке есть тело
    this.clearTargets([this.base, this.mask, this.display]);

    // экранная форма разреза
    this.shapeCanvas = document.createElement('canvas');
    this.shapeTex = new THREE.CanvasTexture(this.shapeCanvas);
    this.shapeTex.minFilter = THREE.LinearFilter;
    this.shapeTex.generateMipmaps = false;
    this.depthRT = null;

    // проход глубины: тело (с уже вырезанными дырами) и черенок
    this.depthScene = new THREE.Scene();
    const depthMat = new THREE.ShaderMaterial({
      uniforms: { carveMask: { value: this.mask.texture } },
      vertexShader: 'varying vec2 vUv;\nvoid main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }',
      fragmentShader: 'uniform sampler2D carveMask;\nvarying vec2 vUv;\nvoid main(){ if (texture2D(carveMask, vUv).r > 0.5) discard; gl_FragColor = vec4(1.0); }',
      side: THREE.FrontSide,
    });
    this.depthMat = depthMat;
    this.depthScene.add(new THREE.Mesh(stage.model.body, depthMat));
    if (stage.model.stem) {
      const stemDepth = new THREE.Mesh(stage.model.stem, new THREE.ShaderMaterial({
        vertexShader: 'varying float vY;\nvoid main(){ vY = position.y; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }',
        fragmentShader: `varying float vY;\nvoid main(){ if (vY < ${stage.stemCut.toFixed(4)}) discard; gl_FragColor = vec4(1.0); }`,
      }));
      this.depthScene.add(stemDepth);
    }

    // проход в UV-пространстве
    this.uvUniforms = {
      opViewProj: { value: new THREE.Matrix4() },
      camPos: { value: new THREE.Vector3() },
      shapeTex: { value: this.shapeTex },
      depthTex: { value: null },
      near: { value: 0.1 },
      far: { value: 50 },
      channel: { value: 0 },
      strength: { value: 1 },
      depthTexel: { value: new THREE.Vector2() },
    };
    this.uvMat = new THREE.ShaderMaterial({
      uniforms: this.uvUniforms,
      vertexShader: `
        uniform mat4 opViewProj;
        varying vec4 vClip; varying vec3 vPos; varying vec3 vNrm;
        void main(){
          vPos = position; vNrm = normal;
          vClip = opViewProj * vec4(position, 1.0);
          gl_Position = vec4(uv * 2.0 - 1.0, 0.0, 1.0);
        }`,
      fragmentShader: `
        uniform sampler2D shapeTex; uniform sampler2D depthTex;
        uniform vec3 camPos; uniform float near; uniform float far;
        uniform int channel; uniform float strength; uniform vec2 depthTexel;
        varying vec4 vClip; varying vec3 vPos; varying vec3 vNrm;
        float lin(float d){ float z = d * 2.0 - 1.0; return 2.0 * near * far / (far + near - z * (far - near)); }
        // самая дальняя глубина в окрестности 3x3: крутые склоны рёбер не «закрывают» сами себя
        float sceneDepth(vec2 s){
          float d = 0.0;
          for (int i = -1; i <= 1; i++) for (int j = -1; j <= 1; j++)
            d = max(d, texture2D(depthTex, s + vec2(float(i), float(j)) * depthTexel).r);
          return d;
        }
        void main(){
          float add = 0.0;
          if (vClip.w > 0.0) {
            vec3 ndc = vClip.xyz / vClip.w;
            vec2 s = ndc.xy * 0.5 + 0.5;
            if (s.x >= 0.0 && s.x <= 1.0 && s.y >= 0.0 && s.y <= 1.0) {
              float facing = dot(normalize(vNrm), normalize(camPos - vPos));
              float tol = 0.03 + 0.12 * (1.0 - clamp(facing, 0.0, 1.0));
              float visible = step(lin(ndc.z * 0.5 + 0.5), lin(sceneDepth(s)) + tol);
              add = texture2D(shapeTex, s).r * step(0.04, facing) * visible;
            }
          }
          gl_FragColor = channel == 0 ? vec4(step(0.5, add), 0.0, 0.0, 0.0) : vec4(0.0, add * strength, 0.0, 0.0);
        }`,
      blending: THREE.CustomBlending,
      blendEquation: THREE.MaxEquation,
      blendSrc: THREE.OneFactor,
      blendDst: THREE.OneFactor,
      depthTest: false,
      depthWrite: false,
      side: THREE.DoubleSide,
    });
    this.uvScene = new THREE.Scene();
    const uvMesh = new THREE.Mesh(stage.model.body, this.uvMat);
    uvMesh.frustumCulled = false;
    this.uvScene.add(uvMesh);
    this.dummyCam = new THREE.Camera();

    // покрытие развёртки
    const covMat = new THREE.ShaderMaterial({
      vertexShader: 'void main(){ gl_Position = vec4(uv * 2.0 - 1.0, 0.0, 1.0); }',
      fragmentShader: 'void main(){ gl_FragColor = vec4(1.0); }',
      side: THREE.DoubleSide, depthTest: false, depthWrite: false, blending: THREE.NoBlending,
    });
    const covScene = new THREE.Scene();
    const covMesh = new THREE.Mesh(stage.model.body, covMat);
    covMesh.frustumCulled = false;
    covScene.add(covMesh);
    this.withState(() => {
      this.renderer.setRenderTarget(this.coverage);
      this.renderer.setClearColor(0x000000, 0);
      this.renderer.clear();
      this.renderer.render(covScene, this.dummyCam);
    });

    // добивка за края островов: пустые тексели берут максимум соседей из тела
    this.dilate = new Quad(`
      uniform sampler2D mask; uniform sampler2D cov; uniform vec2 texel;
      varying vec2 vUv;
      void main(){
        vec4 c = texture2D(mask, vUv);
        if (texture2D(cov, vUv).r < 0.5) {
          c = vec4(0.0);
          for (int dx = -${DILATE}; dx <= ${DILATE}; dx++)
            for (int dy = -${DILATE}; dy <= ${DILATE}; dy++) {
              vec2 q = vUv + vec2(float(dx), float(dy)) * texel;
              if (texture2D(cov, q).r > 0.5) c = max(c, texture2D(mask, q));
            }
        }
        gl_FragColor = c;
      }`, { mask: { value: this.mask.texture }, cov: { value: this.coverage.texture }, texel: { value: new THREE.Vector2(1 / size, 1 / size) } });
    this.copy = new Quad('uniform sampler2D src;\nvarying vec2 vUv;\nvoid main(){ gl_FragColor = texture2D(src, vUv); }', { src: { value: null } });
    this.compose = new Quad(`
      uniform sampler2D through; uniform sampler2D depth;
      varying vec2 vUv;
      void main(){ gl_FragColor = vec4(step(0.5, texture2D(through, vUv).r), texture2D(depth, vUv).r, 0.0, 0.0); }`,
    { through: { value: null }, depth: { value: null } });

    stage.setMask(this.display.texture);
  }

  get texture() { return this.display.texture; }
  get canUndo() { return this.ops.length > 0; }

  withState(fn) {
    const r = this.renderer;
    const prevTarget = r.getRenderTarget();
    const prevAuto = r.autoClear;
    const prevColor = r.getClearColor(new THREE.Color());
    const prevAlpha = r.getClearAlpha();
    try { return fn(); } finally {
      r.setRenderTarget(prevTarget);
      r.autoClear = prevAuto;
      r.setClearColor(prevColor, prevAlpha);
    }
  }

  clearTargets(list) {
    this.withState(() => {
      this.renderer.setClearColor(0x000000, 0);
      for (const t of list) { this.renderer.setRenderTarget(t); this.renderer.clear(); }
    });
  }

  // Нарисовать форму разреза на экранной маске (координаты 0..1, y вниз).
  drawShape(op, w, h) {
    const c = this.shapeCanvas;
    if (c.width !== w || c.height !== h) { c.width = w; c.height = h; }
    const g = c.getContext('2d');
    g.fillStyle = '#000';
    g.fillRect(0, 0, w, h);
    g.fillStyle = g.strokeStyle = '#fff';
    const pts = op.shape.pts;
    if (op.shape.type === 'poly') {
      g.beginPath();
      pts.forEach(([x, y], i) => (i ? g.lineTo(x * w, y * h) : g.moveTo(x * w, y * h)));
      g.closePath();
      g.fill();
    } else {
      g.lineCap = g.lineJoin = 'round';
      g.lineWidth = Math.max(1, op.shape.width * h);
      g.beginPath();
      pts.forEach(([x, y], i) => (i ? g.lineTo(x * w, y * h) : g.moveTo(x * w, y * h)));
      if (pts.length === 1) g.lineTo(pts[0][0] * w + 0.01, pts[0][1] * h);
      g.stroke();
    }
    this.shapeTex.needsUpdate = true;
  }

  // Применить один шаг к цели target, видимость считается по маске maskForDepth.
  runOp(op, target, maskForDepth) {
    const aspect = op.cam.aspect;
    const w = Math.round(aspect >= 1 ? SHAPE_RES : SHAPE_RES * aspect);
    const h = Math.round(aspect >= 1 ? SHAPE_RES / aspect : SHAPE_RES);
    this.drawShape(op, w, h);
    if (!this.depthRT || this.depthRT.width !== w || this.depthRT.height !== h) {
      this.depthRT?.dispose();
      this.depthRT = new THREE.WebGLRenderTarget(w, h, { depthBuffer: true, generateMipmaps: false });
      this.depthRT.depthTexture = new THREE.DepthTexture(w, h);
      this.depthRT.depthTexture.minFilter = this.depthRT.depthTexture.magFilter = THREE.NearestFilter;
    }
    const cam = orbitCamera(op.cam, aspect);
    this.withState(() => {
      const r = this.renderer;
      this.depthMat.uniforms.carveMask.value = maskForDepth.texture;
      r.autoClear = true;
      r.setClearColor(0x000000, 0);
      r.setRenderTarget(this.depthRT);
      r.render(this.depthScene, cam);

      const u = this.uvUniforms;
      u.opViewProj.value.multiplyMatrices(cam.projectionMatrix, cam.matrixWorldInverse);
      u.camPos.value.copy(cam.position);
      u.depthTex.value = this.depthRT.depthTexture;
      u.depthTexel.value.set(1 / w, 1 / h);
      u.near.value = cam.near;
      u.far.value = cam.far;
      u.channel.value = op.knife === 'through' ? 0 : 1;
      u.strength.value = op.strength ?? 1;
      r.autoClear = false;
      r.setRenderTarget(target);
      r.render(this.uvScene, this.dummyCam);
    });
  }

  refreshDisplay() {
    this.withState(() => this.dilate.render(this.renderer, this.display));
  }

  apply(op) {
    if (this.ops.length >= this.maxUndo) {
      // самый старый шаг больше не отменяется: впекаем его в базу
      this.runOp(this.ops.shift(), this.base, this.base);
    }
    this.ops.push(op);
    this.runOp(op, this.mask, this.mask);
    this.refreshDisplay();
  }

  rebuild() {
    this.withState(() => {
      this.copy.material.uniforms.src.value = this.base.texture;
      this.copy.render(this.renderer, this.mask);
    });
    for (const op of this.ops) this.runOp(op, this.mask, this.mask);
    this.refreshDisplay();
  }

  undo() {
    if (!this.ops.length) return false;
    this.ops.pop();
    this.rebuild();
    return true;
  }

  reset() {
    this.ops = [];
    this.clearTargets([this.base]);
    this.rebuild();
  }

  // Загрузить сохранённые маски (PNG в градациях серого, верхняя строка картинки = v 0).
  async loadMasks(throughUrl, depthUrl) {
    const load = (url) => new Promise((res, rej) => new THREE.TextureLoader().load(url, (t) => {
      t.flipY = false; t.generateMipmaps = false; t.minFilter = THREE.NearestFilter; t.magFilter = THREE.NearestFilter;
      t.needsUpdate = true; res(t);
    }, undefined, rej));
    const [t, d] = await Promise.all([load(throughUrl), load(depthUrl)]);
    this.ops = [];
    this.withState(() => {
      this.compose.material.uniforms.through.value = t;
      this.compose.material.uniforms.depth.value = d;
      this.compose.render(this.renderer, this.base);
    });
    t.dispose();
    d.dispose();
    this.rebuild();
  }

  // Маски в PNG (8 бит): {through: Blob, depth: Blob}.
  async exportMasks() {
    const s = this.size;
    const px = new Uint8Array(s * s * 4);
    this.renderer.readRenderTargetPixels(this.mask, 0, 0, s, s, px);
    const toBlob = (channel) => {
      const c = document.createElement('canvas');
      c.width = c.height = s;
      const g = c.getContext('2d');
      const img = g.createImageData(s, s);
      const d = img.data;
      for (let i = 0, n = s * s; i < n; i++) {
        const v = px[i * 4 + channel];
        d[i * 4] = d[i * 4 + 1] = d[i * 4 + 2] = v;
        d[i * 4 + 3] = 255;
      }
      g.putImageData(img, 0, 0); // строка 0 буфера (v = 0) становится верхней строкой картинки
      return new Promise((res) => c.toBlob(res, 'image/png'));
    };
    return { through: await toBlob(0), depth: await toBlob(1) };
  }

  dispose() {
    for (const t of [this.base, this.mask, this.display, this.coverage, this.depthRT]) t?.dispose();
    this.shapeTex.dispose();
  }
}

// ---------------------------------------------------------------- снимок

export async function snapshot(renderer, stage, cam, { size = 1024, dark = false } = {}) {
  const rt = new THREE.WebGLRenderTarget(size, size, { samples: 4, colorSpace: THREE.SRGBColorSpace });
  const camera = orbitCamera(cam, 1);
  const wasDark = stage.dark;
  const wasFlicker = stage.flicker;
  stage.flicker = 1;
  stage.setDark(dark);
  const prev = renderer.getRenderTarget();
  renderer.setRenderTarget(rt);
  renderer.render(stage.scene, camera);
  const px = new Uint8Array(size * size * 4);
  renderer.readRenderTargetPixels(rt, 0, 0, size, size, px);
  renderer.setRenderTarget(prev);
  rt.dispose();
  stage.flicker = wasFlicker;
  stage.setDark(wasDark);
  const c = document.createElement('canvas');
  c.width = c.height = size;
  const g = c.getContext('2d');
  const img = g.createImageData(size, size);
  for (let y = 0; y < size; y++) { // буфер снизу вверх, картинка сверху вниз
    img.data.set(px.subarray((size - 1 - y) * size * 4, (size - y) * size * 4), y * size * 4);
  }
  for (let i = 3; i < img.data.length; i += 4) img.data[i] = 255;
  g.putImageData(img, 0, 0);
  return new Promise((res) => c.toBlob(res, 'image/jpeg', 0.88));
}
