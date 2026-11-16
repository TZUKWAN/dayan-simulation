"""视觉增强补丁 A-D：泛光后处理 / 昼夜循环+车灯 / 数据特效层 / 开场镜头。
全部叠加进 viz3d.js，失败自动降级，不改 scene-studio 合同。"""
import io

p = 'viz3d.js'
s = io.open(p, encoding='utf-8').read()

def rep(tag, old, new, must=True):
    global s
    if old not in s:
        print('MISS:', tag)
        if must:
            raise SystemExit(1)
        return
    s = s.replace(old, new, 1)
    print('OK  :', tag)

# ============ 1) init 后初始化后处理管线 ============
rep('init hook',
    "    buildEnvLighting();   // PMREM IBL：金属/玻璃的真实反射来源\n"
    "    animate();",
    "    buildEnvLighting();   // PMREM IBL：金属/玻璃的真实反射来源\n"
    "    initPostFX();\n"
    "    animate();")

# ============ 2) frame 最终渲染走管线 + 昼夜/特效 tick ============
rep('frame hook',
    "    updateWeather(dt);\n"
    "    if (renderer && sceneObj) renderer.render(sceneObj, camera);\n"
    "  }",
    "    updateWeather(dt);\n"
    "    fxTick(dt, t);\n"
    "    dayCycleTick(dt);\n"
    "    renderFrame();\n"
    "  }")

# ============ 3) 显式 mood 关闭昼夜循环（用户选定的时段优先） ============
rep('setMood pin',
    "  function setMood(moodName, density) {\n"
    "    const cfg = MOODS[moodName] || MOODS.day;",
    "  function setMood(moodName, density) {\n"
    "    window._vizDayCycle = false;   // 显式选定时段 → 固定光照\n"
    "    const cfg = MOODS[moodName] || MOODS.day;")

# ============ 4) 状态场景：默认开循环 + 开场镜头 ============
rep('visualizeState hook',
    "    studioStage=DAYAN_SCENE_STUDIO.stage(scene,studioProfile,stream?.frames?.[0]||{});\n"
    "    renderer.toneMappingExposure=1.05;\n"
    "    buildStateLegend();",
    "    studioStage=DAYAN_SCENE_STUDIO.stage(scene,studioProfile,stream?.frames?.[0]||{});\n"
    "    renderer.toneMappingExposure=1.05;\n"
    "    window._vizDayCycle = (window._vizDayCycle !== false);   // 状态世界默认昼夜流动\n"
    "    DAYCYCLE.ensure();\n"
    "    startIntroCinematic();\n"
    "    buildStateLegend();")

# ============ 5) vizApplyFrame 尾部挂实体特效 ============
rep('applyFrame fx hook',
    "    DAYAN_SCENE_STUDIO.updateStage(studioStage,fr,studioProfile);\n"
    "    meshMap.forEach((m, id) => {",
    "    DAYAN_SCENE_STUDIO.updateStage(studioStage,fr,studioProfile);\n"
    "    updateEntityFX(group, fr);\n"
    "    meshMap.forEach((m, id) => {")

# ============ 6) 事件冲击波钩子（帧切换时检查事件穿越） ============
rep('event hook',
    "    const previous=followingStateEntity?stateEntityMesh(followingStateEntity)?.position.clone():null;\n"
    "    if (idx !== window._vizStateIdx) {\n"
    "      window._vizStateIdx = idx;\n"
    "      vizApplyFrame(st.frames[idx]);",
    "    const previous=followingStateEntity?stateEntityMesh(followingStateEntity)?.position.clone():null;\n"
    "    if (idx !== window._vizStateIdx) {\n"
    "      const prevFr = st.frames[window._vizStateIdx];\n"
    "      window._vizStateIdx = idx;\n"
    "      vizApplyFrame(st.frames[idx]);\n"
    "      if (prevFr) spawnEventWaves(st, prevFr, st.frames[idx]);")

# ============ 7) 导出 ============
rep('export hook',
    "    setMood,\n"
    "    setLayer,\n"
    "    setGroupFilter,\n"
    "    pause,\n"
    "    resume,\n"
    "    get currentType() { return currentScene ? currentScene.type : null; }",
    "    setMood,\n"
    "    setLayer,\n"
    "    setGroupFilter,\n"
    "    pause,\n"
    "    resume,\n"
    "    setPostFX(on){POSTFX.userOn=!!on;if(POSTFX.ready){POSTFX.enabled=POSTFX.userOn;}},\n"
    "    get postFX(){return {enabled:POSTFX.enabled,ready:POSTFX.ready,costMs:POSTFX.costMs};},\n"
    "    setDayCycle(on){window._vizDayCycle=!!on;if(on)DAYCYCLE.ensure();},\n"
    "    setDayPhase(h){DAYCYCLE.h=((Number(h)||0)%24+24)%24;},\n"
    "    get dayPhase(){return DAYCYCLE.h;},\n"
    "    get currentType() { return currentScene ? currentScene.type : null; }")

# ============ 大块：新模块代码（插到导出块前） ============
NEWFX = r'''
  // ============================================================
  // 视觉增强层（2026-11-13）：
  //   A. 轻量泛光后处理（自研，无新依赖；失败自动降级直渲）
  //   B. 昼夜连续循环 + 车灯/环道灯随黑暗渐亮（状态世界默认开启）
  //   C. 数据驱动特效：感染脉冲光环 / 疏散拖尾 / 干预冲击波
  //   D. 开场推近镜头（可交互打断）
  // 特效层只做视觉表现，不产生任何模型数据；provenance 标注不变。
  // ============================================================
  const POSTFX = { ready:false, enabled:false, userOn:true, costMs:0,
                   _avg:0, _frames:0, rtA:null, rtB:null, rtS:null,
                   camQuad:null, scBright:null, scBlur:null, scComp:null,
                   quad:null, sceneQuad:null };

  function initPostFX() {
    if (!renderer || POSTFX.ready || POSTFX.tried) return;
    POSTFX.tried = true;
    try {
      const size = renderer.getSize(new THREE.Vector2());
      const mkRT = (w, h, type) => new THREE.WebGLRenderTarget(
        Math.max(2, Math.floor(w)), Math.max(2, Math.floor(h)),
        { type: type, depthBuffer: true, stencilBuffer: false });
      const type = (renderer.capabilities.isWebGL2 &&
                    renderer.extensions.get('EXT_color_buffer_float'))
        ? THREE.HalfFloatType : THREE.UnsignedByteType;
      POSTFX.rtS = mkRT(size.x, size.y, type);
      POSTFX.rtA = mkRT(size.x / 4, size.y / 4, type);
      POSTFX.rtB = mkRT(size.x / 4, size.y / 4, type);
      POSTFX.scBright = new THREE.ShaderMaterial({
        uniforms: { tDiffuse: { value: null }, uThresh: { value: 0.68 } },
        vertexShader: POST_VERT, fragmentShader: POST_BRIGHT });
      POSTFX.scBlur = new THREE.ShaderMaterial({
        uniforms: { tDiffuse: { value: null }, uDir: { value: new THREE.Vector2(1, 0) },
                    uTexel: { value: new THREE.Vector2(1 / POSTFX.rtA.width, 1 / POSTFX.rtA.height) } },
        vertexShader: POST_VERT, fragmentShader: POST_BLUR });
      POSTFX.scComp = new THREE.ShaderMaterial({
        uniforms: { tScene: { value: null }, tBloom: { value: null },
                    uBloom: { value: 0.85 }, uVig: { value: 0.32 },
                    uSat: { value: 1.07 } },
        vertexShader: POST_VERT, fragmentShader: POST_COMP });
      POSTFX.quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), POSTFX.scBright);
      POSTFX.sceneQuad = new THREE.Scene();
      POSTFX.camQuad = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
      POSTFX.sceneQuad.add(POSTFX.quad);
      POSTFX.ready = true;
      POSTFX.enabled = POSTFX.userOn;
      window.addEventListener('resize', () => resizePostFX());
    } catch (e) {
      console.warn('[viz3d] 后处理初始化失败，降级直渲:', e);
      POSTFX.ready = false; POSTFX.enabled = false;
    }
  }

  function resizePostFX() {
    if (!POSTFX.ready || !renderer) return;
    const size = renderer.getSize(new THREE.Vector2());
    [POSTFX.rtS, POSTFX.rtA, POSTFX.rtB].forEach(rt => rt.dispose());
    const type = POSTFX.rtS.texture.type;
    POSTFX.rtS = new THREE.WebGLRenderTarget(Math.max(2, size.x | 0), Math.max(2, size.y | 0), { type, depthBuffer: true });
    POSTFX.rtA = new THREE.WebGLRenderTarget(Math.max(2, size.x >> 2), Math.max(2, size.y >> 2), { type });
    POSTFX.rtB = new THREE.WebGLRenderTarget(Math.max(2, size.x >> 2), Math.max(2, size.y >> 2), { type });
    POSTFX.scBlur.uniforms.uTexel.value.set(1 / POSTFX.rtA.width, 1 / POSTFX.rtA.height);
  }

  function _fsQuad(mat) {
    POSTFX.quad.material = mat;
    renderer.setRenderTarget(null);
  }

  function renderFrame() {
    if (!renderer || !sceneObj) return;
    if (!POSTFX.enabled || !POSTFX.ready) {
      renderer.render(sceneObj, camera);
      return;
    }
    const t0 = performance.now();
    // 场景 → rtS
    renderer.setRenderTarget(POSTFX.rtS);
    renderer.render(sceneObj, camera);
    // 亮通
    POSTFX.scBright.uniforms.tDiffuse.value = POSTFX.rtS.texture;
    _fsQuad(POSTFX.scBright);
    renderer.setRenderTarget(POSTFX.rtA);
    renderer.render(POSTFX.sceneQuad, POSTFX.camQuad);
    // 高斯 H/V（两遍 1/4 分辨率）
    POSTFX.scBlur.uniforms.tDiffuse.value = POSTFX.rtA.texture;
    POSTFX.scBlur.uniforms.uDir.value.set(1, 0);
    _fsQuad(POSTFX.scBlur);
    renderer.setRenderTarget(POSTFX.rtB);
    renderer.render(POSTFX.sceneQuad, POSTFX.camQuad);
    POSTFX.scBlur.uniforms.tDiffuse.value = POSTFX.rtB.texture;
    POSTFX.scBlur.uniforms.uDir.value.set(0, 1);
    _fsQuad(POSTFX.scBlur);
    renderer.setRenderTarget(POSTFX.rtA);
    renderer.render(POSTFX.sceneQuad, POSTFX.camQuad);
    // 合成（泛光叠加 + 暗角 + 饱和微调）
    POSTFX.scComp.uniforms.tScene.value = POSTFX.rtS.texture;
    POSTFX.scComp.uniforms.tBloom.value = POSTFX.rtA.texture;
    _fsQuad(POSTFX.scComp);
    renderer.setRenderTarget(null);
    renderer.render(POSTFX.sceneQuad, POSTFX.camQuad);
    // 性能看门狗：连续超阈值自动关（保留直渲底线）
    POSTFX.costMs = performance.now() - t0;
    POSTFX._avg = POSTFX._avg * 0.95 + POSTFX.costMs * 0.05;
    if (++POSTFX._frames > 90 && POSTFX._avg > 22) {
      POSTFX.enabled = false;
      if (window.DAYAN_EVENT) DAYAN_EVENT('warn', '泛光已自动关闭',
        '本机 GPU 负载过高（' + POSTFX._avg.toFixed(1) + 'ms/帧），已降级直渲保帧率');
    }
  }

  const POST_VERT = [
    'varying vec2 vUv;',
    'void main(){ vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }'].join('\n');
  const POST_BRIGHT = [
    'varying vec2 vUv; uniform sampler2D tDiffuse; uniform float uThresh;',
    'void main(){',
    '  vec3 c = texture2D(tDiffuse, vUv).rgb;',
    '  float l = dot(c, vec3(0.299, 0.587, 0.114));',
    '  float w = smoothstep(uThresh, uThresh + 0.35, l);',
    '  gl_FragColor = vec4(c * w * w, 1.0);',
    '}'].join('\n');
  const POST_BLUR = [
    'varying vec2 vUv; uniform sampler2D tDiffuse; uniform vec2 uDir; uniform vec2 uTexel;',
    'void main(){',
    '  vec2 o = uDir * uTexel;',
    '  vec3 s = texture2D(tDiffuse, vUv).rgb * 0.227;',
    '  s += (texture2D(tDiffuse, vUv + o * 1.384).rgb + texture2D(tDiffuse, vUv - o * 1.384).rgb) * 0.316;',
    '  s += (texture2D(tDiffuse, vUv + o * 3.230).rgb + texture2D(tDiffuse, vUv - o * 3.230).rgb) * 0.070;',
    '  gl_FragColor = vec4(s, 1.0);',
    '}'].join('\n');
  const POST_COMP = [
    'varying vec2 vUv; uniform sampler2D tScene; uniform sampler2D tBloom;',
    'uniform float uBloom; uniform float uVig; uniform float uSat;',
    'void main(){',
    '  vec3 c = texture2D(tScene, vUv).rgb;',
    '  c += texture2D(tBloom, vUv).rgb * uBloom;',
    '  float l = dot(c, vec3(0.299, 0.587, 0.114));',
    '  c = mix(vec3(l), c, uSat);',
    '  vec2 d = vUv - 0.5;',
    '  c *= 1.0 - uVig * smoothstep(0.18, 0.78, dot(d, d) * 2.4);',
    '  gl_FragColor = vec4(c, 1.0);',
    '}'].join('\n');

  // ---------- B. 昼夜循环 ----------
  const DAYCYCLE = {
    h: 9.2, ensureDone: false, lamps: [], lights: [],
    ensure() {
      if (this.ensureDone || !sceneObj) return;
      this.ensureDone = true;
      if (!window._vizLights || !window._vizLights.key) {
        const key = new THREE.DirectionalLight(0xfff2e0, 1.2);
        key.position.set(24, 40, 14);
        sceneObj.add(key);
        const hemi = new THREE.HemisphereLight(0x9ab8e0, 0x4a4a44, 0.7);
        sceneObj.add(hemi);
        window._vizLights = Object.assign(window._vizLights || {},
          { key, hemi });
      }
      if (!sceneObj.fog) {
        sceneObj.fog = new THREE.Fog(0x8ab4dc, 70, 340);
      }
    },
  };

  function dayCycleTick(dt) {
    if (!window._vizDayCycle || !sceneObj) return;
    DAYCYCLE.ensure();
    DAYCYCLE.h = (DAYCYCLE.h + dt * (24 / 160)) % 24;   // 160 秒一昼夜
    applyDayPhase(DAYCYCLE.h);
  }

  function _lerpC(a, b, w) { return a.clone().lerp(b, Math.max(0, Math.min(1, w))); }
  function _mix3(ca, cb, cc, wDay, wDusk) {
    // night=cc, dusk=cb, day=ca：先夜→暮（wDusk），再暮→昼（wDay）
    const base = _lerpC(cc, cb, wDusk);
    return _lerpC(base, ca, wDay);
  }

  function applyDayPhase(h) {
    // 权重：分段把 24h 映射到 day/dusk/night 三锚
    let wDay = 0, wDusk = 0;
    if (h >= 7 && h < 17) { wDay = 1; }
    else if (h >= 5 && h < 7) { wDusk = 1 - (h - 5) / 2; wDay = (h - 5) / 2; }
    else if (h >= 17 && h < 20) { wDay = 1 - (h - 17) / 3; wDusk = (h - 17) / 3; }
    const dark = Math.max(0, Math.min(1, 1 - wDay - wDusk * 0.55));
    window._vizDarkness = dark;

    const day = MOODS.day, dusk = MOODS.dusk, night = MOODS.night;
    const _c = (x) => new THREE.Color(x);
    // 天穹三段渐变
    const dome = sceneObj.children.find(c => c.geometry && c.geometry.type === 'SphereGeometry' && c.material && c.material.map);
    if (dome && dome.material.map) {
      const stops = [0, 0.58, 1].map((_, i) => {
        const cn = _c(night.dome[i]), cd = _c(dusk.dome[i]), cl = _c(day.dome[i]);
        return _mix3(cl, cd, cn, wDay, wDusk).getStyle();
      });
      const c2 = document.createElement('canvas');
      c2.width = 4; c2.height = 256;
      const g2 = c2.getContext('2d');
      const gr2 = g2.createLinearGradient(0, 0, 0, 256);
      gr2.addColorStop(0, stops[0]); gr2.addColorStop(0.58, stops[1]); gr2.addColorStop(1, stops[2]);
      g2.fillStyle = gr2; g2.fillRect(0, 0, 4, 256);
      dome.material.map.image = c2;
      dome.material.map.needsUpdate = true;
    }
    sceneObj.background = _mix3(_c(day.bg), _c(dusk.bg), _c(night.bg), wDay, wDusk);
    sceneObj.fog.color = _mix3(_c(day.fog[0]), _c(dusk.fog[0]), _c(night.fog[0]), wDay, wDusk);
    sceneObj.fog.near = night.fog[1] + (day.fog[1] - night.fog[1]) * wDay;
    sceneObj.fog.far = night.fog[2] + (day.fog[2] - night.fog[2]) * wDay;
    const L = window._vizLights || {};
    if (L.key) {
      L.key.intensity = night.key[1] + (day.key[1] - night.key[1]) * wDay;
      L.key.color = _mix3(_c(day.key[0]), _c(dusk.key[0]), _c(night.key[0]), wDay, wDusk);
      // 太阳随时间绕场：黄昏/清晨角度低、色暖
      const ang = ((h - 6) / 12) * Math.PI;   // 6h→0, 18h→π
      L.key.position.set(Math.cos(ang) * 46, Math.max(6, Math.sin(ang) * 44), 18);
    }
    if (L.hemi) {
      L.hemi.intensity = night.hemi[2] + (day.hemi[2] - night.hemi[2]) * wDay;
      L.hemi.color = _mix3(_c(day.hemi[0]), _c(dusk.hemi[0]), _c(night.hemi[0]), wDay, wDusk);
    }
    if (renderer) renderer.toneMappingExposure =
      night.exposure + (day.exposure - night.exposure) * wDay;
    // 灯火随黑暗渐亮
    DAYCYCLE.lamps.forEach(sp => { sp.material.opacity = 0.18 + dark * 0.8; });
    DAYCYCLE.lights.forEach(lt => { lt.intensity = dark * lt.userData.maxI; });
  }

  function ensureNightLights(scene) {
    if (DAYCYCLE.lights.length) return;
    // 预算内真点光：环道 4 角 + 场心，夜晚点亮
    const spots = [[-30, 0, -30], [30, 0, -30], [-30, 0, 30], [30, 0, 30], [0, 0, 0]];
    spots.forEach(([x, , z]) => {
      const pl = new THREE.PointLight(0xffd98c, 0, 42, 1.8);
      pl.position.set(x, 7, z);
      pl.userData.maxI = 1.15;
      scene.add(pl);
      DAYCYCLE.lights.push(pl);
      const sp = new THREE.Sprite(new THREE.SpriteMaterial({
        map: makeGlowTexture('#ffd98c'), color: 0xffd98c,
        transparent: true, opacity: 0.2, depthWrite: false,
        blending: THREE.AdditiveBlending }));
      sp.scale.set(7, 7, 1); sp.position.set(x, 7, z);
      scene.add(sp);
      DAYCYCLE.lamps.push(sp);
    });
  }

  // ---------- C. 数据驱动特效 ----------
  const FXREG = { halos: [], trails: [], waves: [] };

  function _fxHalo(colorHex) {
    const sp = new THREE.Sprite(new THREE.SpriteMaterial({
      map: makeGlowTexture('#ff6a8a'), color: colorHex,
      transparent: true, opacity: 0.0, depthWrite: false,
      blending: THREE.AdditiveBlending }));
    sp.scale.set(2.6, 2.6, 1);
    sp.userData.isFxHalo = true;
    return sp;
  }

  function updateEntityFX(group, fr) {
    if (window._vizDayCycle && studioProfile?.kind === 'ring-road') {
      ensureNightLights(getScene());
    }
    const dark = window._vizDarkness || 0;
    let haloN = 0, trailN = 0;
    (fr.entities || []).slice(0, 3000).forEach(ent => {
      const m = stateEntityMesh(ent.id);
      if (!m) return;
      // --- 车灯（夜）+ 刹车闪红 ---
      if (ent.type === 'car') {
        if (!m.userData.lightsFx) {
          const head = new THREE.Group();
          [-0.34, 0.34].forEach(off => {
            const sp = new THREE.Sprite(new THREE.SpriteMaterial({
              map: makeGlowTexture('#fff3d0'), color: 0xfff3d0,
              transparent: true, opacity: 0.95, depthWrite: false,
              blending: THREE.AdditiveBlending }));
            sp.scale.set(1.5, 1.1, 1); sp.position.set(1.05, 0.05, off);
            head.add(sp);
          });
          const tail = new THREE.Group();
          [-0.34, 0.34].forEach(off => {
            const sp = new THREE.Sprite(new THREE.SpriteMaterial({
              map: makeGlowTexture('#ff4d5f'), color: 0xff4d5f,
              transparent: true, opacity: 0.85, depthWrite: false,
              blending: THREE.AdditiveBlending }));
            sp.scale.set(0.85, 0.6, 1); sp.position.set(-1.05, 0.05, off);
            sp.userData.isTail = true;
            tail.add(sp);
          });
          m.add(head); m.add(tail);
          m.userData.lightsFx = { head, tail };
        }
        const on = dark > 0.45 && m.visible;
        m.userData.lightsFx.head.visible = on;
        m.userData.lightsFx.tail.visible = on;
        if (on) {
          const prev = m.userData.prevSpeed;
          const braking = typeof prev === 'number' &&
            typeof ent.speed === 'number' && (prev - ent.speed) > 0.55;
          m.userData.lightsFx.tail.children.forEach(sp => {
            sp.material.opacity = braking ? 1.0 : 0.55;
            sp.scale.set(braking ? 1.5 : 0.85, braking ? 1.0 : 0.6, 1);
          });
        }
        m.userData.prevSpeed = ent.speed;
      }
      // --- 感染脉冲光环：状态 I*/infected，或携带 I>0 的个体 ---
      const infected = ent.state === 'infected' || ent.state === 'I' ||
        (typeof ent.infected === 'number' && ent.infected > 0.5) ||
        (ent.state && /^I[_=]/.test(String(ent.state)));
      if (infected && haloN < 120 && studioProfile?.kind !== 'cohorts') {
        if (!m.userData.halo) {
          m.userData.halo = _fxHalo(0xff5d80);
          m.add(m.userData.halo);
          FXREG.halos.push(m.userData.halo);
        }
        m.userData.halo.visible = true;
        m.userData.halo.position.set(0, 1.5, 0);
        haloN++;
      } else if (m.userData.halo) {
        m.userData.halo.visible = false;
      }
      // --- 疏散拖尾：运动中的行人，位置环形缓冲 ---
      if (ent.type === 'pedestrian' && ent.state === 'moving' &&
          m.visible && trailN < 30) {
        if (!m.userData.trailLine) {
          const g = new THREE.BufferGeometry();
          g.setAttribute('position', new THREE.Float32BufferAttribute(
            new Float32Array(18), 3));
          const line = new THREE.Line(g, new THREE.LineBasicMaterial({
            color: 0x9fe8ff, transparent: true, opacity: 0.4,
            depthWrite: false }));
          line.userData.isFxTrail = true;
          line.frustumCulled = false;
          group.add(line);
          m.userData.trailLine = line;
          m.userData.trailPts = [];
          FXREG.trails.push(line);
        }
        const pts = m.userData.trailPts;
        pts.push(m.position.x, m.position.y, m.position.z);
        while (pts.length > 18) { pts.shift(); pts.shift(); pts.shift(); }
        const arr = m.userData.trailLine.geometry.attributes.position.array;
        const seg = pts.length / 3;
        for (let i = 0; i < 6; i++) {
          const j = seg - 6 + i;   // 最近 6 个保存位置；不足用当前位置补齐
          arr[i * 3] = j >= 0 ? pts[j * 3] : m.position.x;
          arr[i * 3 + 1] = j >= 0 ? pts[j * 3 + 1] : m.position.y;
          arr[i * 3 + 2] = j >= 0 ? pts[j * 3 + 2] : m.position.z;
        }
        m.userData.trailLine.geometry.attributes.position.needsUpdate = true;
        m.userData.trailLine.visible = true;
        trailN++;
      } else if (m.userData.trailLine) {
        m.userData.trailLine.visible = false;
      }
    });
  }

  function spawnEventWaves(st, prevFr, fr) {
    if (!st.events || !st.events.length) return;
    const t0 = prevFr ? (prevFr.sim_t ?? -1e9) : -1e9;
    const t1 = fr.sim_t ?? 1e9;
    st.events.forEach(ev => {
      const et = ev.sim_t ?? ev.t;
      if (typeof et !== 'number' || et <= t0 || et > t1) return;
      if (FXREG.waves.length >= 2) return;
      const ring = new THREE.Mesh(
        new THREE.RingGeometry(0.8, 1.15, 48),
        new THREE.MeshBasicMaterial({ color: 0xffc85a, transparent: true,
          opacity: 0.75, side: THREE.DoubleSide, depthWrite: false }));
      ring.rotation.x = -Math.PI / 2;
      ring.position.set(0, 0.25, 0);
      ring.userData.isFxWave = { born: performance.now() };
      getScene().add(ring);
      FXREG.waves.push(ring);
      if (window.DAYAN_EVENT) DAYAN_EVENT('',
        '干预生效 · 冲击波标记', (ev.label || '') + ' sim_t=' + (+et).toFixed(2));
    });
  }

  function fxTick(dt, t) {
    // 感染光环呼吸
    const now = performance.now();
    FXREG.halos.forEach(sp => {
      if (!sp.visible) return;
      const k = 0.55 + 0.45 * Math.sin(now * 0.004 + sp.id);
      sp.material.opacity = 0.32 + 0.4 * k;
      const sc = 2.3 + 0.9 * k;
      sp.scale.set(sc, sc, 1);
    });
    // 冲击波扩散
    for (let i = FXREG.waves.length - 1; i >= 0; i--) {
      const ring = FXREG.waves[i];
      const age = (now - ring.userData.isFxWave.born) / 900;
      if (age >= 1) {
        getScene().remove(ring);
        ring.geometry.dispose(); ring.material.dispose();
        FXREG.waves.splice(i, 1);
        continue;
      }
      const r = 0.8 + age * 24;
      ring.scale.set(r, r, 1);
      ring.material.opacity = 0.75 * (1 - age);
    }
  }

  // ---------- D. 开场推近镜头 ----------
  const INTRO = { active: false, t0: 0, dur: 3200, from: null, to: null };
  function startIntroCinematic() {
    if (!camera || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    INTRO.to = camera.position.clone();
    INTRO.from = INTRO.to.clone().multiplyScalar(2.4).add(
      new THREE.Vector3(0, INTRO.to.y * 0.9, 0));
    INTRO.t0 = performance.now();
    INTRO.active = true;
  }
  function introTick() {
    if (!INTRO.active || !camera) return;
    const a = Math.min(1, (performance.now() - INTRO.t0) / INTRO.dur);
    const e = 1 - Math.pow(1 - a, 3);   // easeOutCubic
    camera.position.lerpVectors(INTRO.from, INTRO.to, e);
    camera.lookAt(0, 0, 0);
    if (a >= 1) INTRO.active = false;
  }
  window.addEventListener('pointerdown', () => { INTRO.active = false; }, { once: false });

  window._vizDayCycle = true;

'''

rep('insert FX module',
    '  // ---- 导出到全局 ----',
    NEWFX + '\n  // ---- 导出到全局 ----')

# frame() 里补开场镜头 tick（放 fxTick 后）
rep('intro tick hook',
    "    fxTick(dt, t);\n"
    "    dayCycleTick(dt);\n"
    "    renderFrame();",
    "    fxTick(dt, t);\n"
    "    dayCycleTick(dt);\n"
    "    introTick();\n"
    "    renderFrame();")

io.open(p, 'w', encoding='utf-8').write(s)
print('--- viz3d.js saved ---')
PYEOF = None
