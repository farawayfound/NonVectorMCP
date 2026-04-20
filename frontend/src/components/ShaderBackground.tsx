import { useEffect, useRef } from "react";

export function ShaderBackground() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const gl = canvas.getContext("webgl", {
      antialias: true,
      premultipliedAlpha: false,
      preserveDrawingBuffer: false,
    });
    if (!gl) return;
    gl.getExtension("OES_standard_derivatives");

    function compile(src: string, type: number) {
      const s = gl!.createShader(type)!;
      gl!.shaderSource(s, src);
      gl!.compileShader(s);
      if (!gl!.getShaderParameter(s, gl!.COMPILE_STATUS)) {
        console.error(gl!.getShaderInfoLog(s));
        throw new Error("shader compile");
      }
      return s;
    }

    function makeProgram(vs: string, fs: string) {
      const p = gl!.createProgram()!;
      gl!.attachShader(p, compile(vs, gl!.VERTEX_SHADER));
      gl!.attachShader(p, compile(fs, gl!.FRAGMENT_SHADER));
      gl!.linkProgram(p);
      if (!gl!.getProgramParameter(p, gl!.LINK_STATUS)) {
        console.error(gl!.getProgramInfoLog(p));
        throw new Error("link fail");
      }
      return p;
    }

    const VS = `
attribute vec2 aPos;
void main() {
  gl_Position = vec4(aPos, 0.0, 1.0);
}`;

    const FS = `#extension GL_OES_standard_derivatives : enable
precision highp float;
uniform vec2 uRes;
uniform vec2 uMouse;
uniform vec2 uMouseVel;
uniform float uTime;
uniform float uClick;
uniform vec2 uClickPos;
uniform float uClickAge;

float hash12(vec2 p) { return fract(sin(dot(p, vec2(12.9898,78.233)))*43758.5453); }
float noise(vec2 p) {
  vec2 i = floor(p); vec2 f = fract(p);
  vec2 u = f*f*(3.0-2.0*f);
  return mix(mix(hash12(i), hash12(i+vec2(1,0)), u.x),
             mix(hash12(i+vec2(0,1)), hash12(i+vec2(1,1)), u.x), u.y);
}
float fbm(vec2 p) {
  float v = 0.0; float a = 0.5;
  for (int i = 0; i < 5; i++) { v += a * noise(p); p *= 2.02; a *= 0.5; }
  return v;
}

const vec3 INK       = vec3(0.045, 0.040, 0.032);
const vec3 INK_DEEP  = vec3(0.020, 0.017, 0.012);
const vec3 SOIL_WARM = vec3(0.120, 0.095, 0.060);
const vec3 PARCHMENT = vec3(0.929, 0.898, 0.816);
const vec3 TAN       = vec3(0.604, 0.557, 0.463);
const vec3 GOLD      = vec3(0.784, 0.604, 0.235);
const vec3 GOLD_DEEP = vec3(0.690, 0.518, 0.157);
const vec3 SAGE      = vec3(0.353, 0.620, 0.322);
const float PITCH = 0.22;
const float PEAK_HEIGHT = 0.55;

float baseHeight(vec2 p) {
  float t = uTime * 0.020;
  float h = fbm(p * 1.15 + vec2(t, -t*0.7));
  h += 0.55 * fbm(p * 2.50 - vec2(t*0.5, t*0.2));
  h += 0.22 * fbm(p * 5.10 + vec2(-t*0.3, t*0.6));
  return h - 0.35;
}
float peakAt(vec2 p, vec2 apex, float amp) {
  vec2 d = p - apex;
  float r2 = dot(d, d);
  return amp * (exp(-r2*16.0) + exp(-r2*3.0)*0.55);
}
float crater(vec2 p, vec2 cp) {
  vec2 d = p - cp;
  float r2 = dot(d, d);
  float r = sqrt(r2);
  float env = exp(-uClickAge * 1.1);
  float shape = exp(-r2*9.0)*0.8 + exp(-r2*45.0)*0.4;
  float craterH = -env * shape * 0.60;
  float front = 0.55 * uClickAge;
  float x = r - front;
  float rippleH = exp(-x*x*40.0) * sin(x*28.0) * exp(-uClickAge*0.85) * exp(-front*1.3) * 0.08;
  return craterH + rippleH;
}

void main() {
  vec2 uv = (gl_FragCoord.xy - 0.5*uRes) / min(uRes.x, uRes.y);
  vec2 m  = (uMouse    - 0.5) * vec2(uRes.x/min(uRes.x,uRes.y), uRes.y/min(uRes.x,uRes.y));
  vec2 cp = (uClickPos - 0.5) * vec2(uRes.x/min(uRes.x,uRes.y), uRes.y/min(uRes.x,uRes.y));

  float peakAmp = PEAK_HEIGHT * (1.0 + clamp(length(uMouseVel)*0.5, 0.0, 0.4));

  vec2 samplePos = uv;
  for (int i = 0; i < 3; i++) {
    float hb = baseHeight(samplePos);
    samplePos = uv - vec2(0.0, hb * PITCH);
  }
  float h = baseHeight(samplePos) + peakAt(uv, m, peakAmp) + crater(uv, cp);

  float f = h * 42.0;
  float lw = fwidth(f) * 0.9;
  float contour = 1.0 - smoothstep(lw, lw + 0.02, abs(fract(f) - 0.5));
  float isIndex = step(mod(floor(f + 0.5), 5.0), 0.5);

  vec3 bg = mix(INK_DEEP, INK, smoothstep(-0.5, 0.0, h));
  bg = mix(bg, SOIL_WARM * 0.4, smoothstep(0.15, 0.6, h));

  float dhx = dFdx(h) * 55.0;
  float dhy = dFdy(h) * 55.0;
  vec3 n = normalize(vec3(-dhx, -dhy, 1.0));
  float diff = clamp(dot(n, normalize(vec3(-0.55, 0.75, 0.55))), 0.0, 1.0);
  bg *= 0.55 + diff * 0.9;
  bg *= 1.0 - peakAt(uv - vec2(0.12, -0.10), m, peakAmp) * 0.55;

  vec3 lineCol = mix(TAN, PARCHMENT, smoothstep(-0.2, 0.35, h));
  lineCol = mix(lineCol, GOLD, smoothstep(0.45, 0.85, h));
  lineCol = mix(lineCol, PARCHMENT, isIndex * 0.25);
  float craterDepth = max(0.0, -crater(uv, cp));
  lineCol = mix(lineCol, SAGE, min(craterDepth * 2.0, 0.5));

  vec3 col = mix(bg, lineCol, contour * mix(0.28, 0.42, isIndex));
  col += smoothstep(0.45, 0.80, peakAt(uv, m, peakAmp) / peakAmp) * GOLD_DEEP * 0.18;
  col *= 1.0 - craterDepth * 0.9;
  col *= smoothstep(1.85, 0.25, length(uv));
  col += (hash12(gl_FragCoord.xy + uTime) - 0.5) * 0.010;

  gl_FragColor = vec4(col, 1.0);
}`;

    const prog = makeProgram(VS, FS);
    gl.useProgram(prog);

    const aPos      = gl.getAttribLocation(prog, "aPos");
    const uRes      = gl.getUniformLocation(prog, "uRes");
    const uMouse    = gl.getUniformLocation(prog, "uMouse");
    const uMouseVel = gl.getUniformLocation(prog, "uMouseVel");
    const uTime     = gl.getUniformLocation(prog, "uTime");
    const uClick    = gl.getUniformLocation(prog, "uClick");
    const uClickPos = gl.getUniformLocation(prog, "uClickPos");
    const uClickAge = gl.getUniformLocation(prog, "uClickAge");

    const quad = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, quad);
    gl.bufferData(
      gl.ARRAY_BUFFER,
      new Float32Array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1]),
      gl.STATIC_DRAW
    );

    const mouse = { x: 0.5, y: 0.5, px: 0.5, py: 0.5, vx: 0, vy: 0 };
    const click = { amount: 0, pos: { x: 0.5, y: 0.5 }, age: 999 };

    function resize() {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width  = Math.floor(window.innerWidth  * dpr);
      canvas.height = Math.floor(window.innerHeight * dpr);
      gl.viewport(0, 0, canvas.width, canvas.height);
    }

    const onMove  = (e: PointerEvent) => {
      mouse.x = e.clientX / window.innerWidth;
      mouse.y = 1.0 - e.clientY / window.innerHeight;
    };
    const onDown  = (e: PointerEvent) => {
      click.amount = 1;
      click.age = 0;
      click.pos = { x: e.clientX / window.innerWidth, y: 1.0 - e.clientY / window.innerHeight };
    };
    const onResize = () => resize();

    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerdown", onDown);
    window.addEventListener("resize", onResize);
    resize();

    const start = performance.now();
    let lastT = start;
    let rafId = 0;

    function frame(now: number) {
      const dt = Math.min(0.05, (now - lastT) / 1000);
      lastT = now;

      mouse.vx = mouse.x - mouse.px;
      mouse.vy = mouse.y - mouse.py;
      mouse.px += (mouse.x - mouse.px) * 0.15;
      mouse.py += (mouse.y - mouse.py) * 0.15;

      click.amount *= Math.pow(0.1, dt * 0.6);
      if (click.amount < 0.002) click.amount = 0;
      click.age += dt;

      gl.useProgram(prog);
      gl.bindBuffer(gl.ARRAY_BUFFER, quad);
      gl.enableVertexAttribArray(aPos);
      gl.vertexAttribPointer(aPos, 2, gl.FLOAT, false, 0, 0);

      gl.uniform2f(uRes,      canvas.width, canvas.height);
      gl.uniform2f(uMouse,    mouse.px, mouse.py);
      gl.uniform2f(uMouseVel, mouse.vx * 8.0, mouse.vy * 8.0);
      gl.uniform1f(uTime,     (now - start) / 1000);
      gl.uniform1f(uClick,    click.amount);
      gl.uniform2f(uClickPos, click.pos.x, click.pos.y);
      gl.uniform1f(uClickAge, click.age);

      gl.drawArrays(gl.TRIANGLES, 0, 6);
      rafId = requestAnimationFrame(frame);
    }
    rafId = requestAnimationFrame(frame);

    return () => {
      cancelAnimationFrame(rafId);
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerdown", onDown);
      window.removeEventListener("resize", onResize);
      gl.deleteProgram(prog);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      style={{
        position: "fixed",
        inset: 0,
        width: "100vw",
        height: "100vh",
        display: "block",
        zIndex: -1,
        pointerEvents: "none",
      }}
    />
  );
}
