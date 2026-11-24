// Globe 3D de la page vitrine : terres en points, sites d'une chaîne d'approvisionnement reliés par des arcs,
// et petits signaux colorés (médias, météo, marchés) qui circulent vers l'usine.
// Pensé pour rester léger et calme : un seul rendu WebGL, 4 objets dessinés, rotation lente, pause hors écran
// ou onglet caché, image fixe si l'utilisateur a demandé moins d'animations (prefers-reduced-motion).
import { useEffect, useRef } from "react";
import * as THREE from "three";
import { TERRE } from "./globeTerre";

type Site = [nom: string, lat: number, lon: number];

// Chaîne de démonstration (fictive) : principes actifs d'Asie, ports, usines européennes.
const SITES: Record<string, Site> = {
  taizhou: ["Taizhou", 28.66, 121.42], shaoxing: ["Shaoxing", 30.0, 120.58], hyderabad: ["Hyderabad", 17.39, 78.49],
  nhava: ["Nhava Sheva", 18.95, 72.95], shanghai: ["Shanghai", 31.23, 121.49], kaohsiung: ["Kaohsiung", 22.62, 120.3],
  anvers: ["Anvers", 51.27, 4.34], rotterdam: ["Rotterdam", 51.95, 4.14], lehavre: ["Le Havre", 49.48, 0.13],
  bergame: ["Bergame", 45.7, 9.67], mayence: ["Mayence", 50.0, 8.27], lodz: ["Lodz", 51.76, 19.46],
  savannah: ["Savannah", 32.08, -81.09], austin: ["Austin", 30.27, -97.74], tours: ["Tours", 47.39, 0.69],
  cork: ["Cork", 51.9, -8.47],
};
const LIENS: [string, string][] = [
  ["taizhou", "hyderabad"], ["shaoxing", "shanghai"], ["hyderabad", "nhava"], ["nhava", "anvers"], ["shanghai", "anvers"],
  ["kaohsiung", "rotterdam"], ["austin", "savannah"], ["savannah", "rotterdam"], ["rotterdam", "mayence"],
  ["anvers", "tours"], ["anvers", "cork"], ["lehavre", "tours"], ["bergame", "tours"], ["mayence", "tours"], ["lodz", "cork"],
];
const USINES = new Set(["tours", "cork"]);
const TOUCHE = "hyderabad";
// Charte : moutarde (médias), olive (météo), bleu canard éclairci pour rester lisible sur fond sombre (marchés).
const SIGNAUX = ["#ECB920", "#A2B153", "#5FC4CF"];

const RAD = Math.PI / 180;
function versVecteur(lat: number, lon: number, r = 1): THREE.Vector3 {
  return new THREE.Vector3(r * Math.cos(lat * RAD) * Math.cos(lon * RAD), r * Math.sin(lat * RAD), -r * Math.cos(lat * RAD) * Math.sin(lon * RAD));
}

function pointsTerre(): Float32Array {
  const n = TERRE.length / 4;
  const pos = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) {
    const lat = parseInt(TERRE.slice(i * 4, i * 4 + 2), 36) / 2 - 90;
    const lon = parseInt(TERRE.slice(i * 4 + 2, i * 4 + 4), 36) / 2 - 180;
    versVecteur(lat, lon, 1.002).toArray(pos, i * 3);
  }
  return pos;
}

/** Arc en grand cercle entre deux sites, surélevé au milieu (d'autant plus que les sites sont éloignés). */
function arc(a: Site, b: Site, segments = 48): THREE.Vector3[] {
  const va = versVecteur(a[1], a[2]);
  const vb = versVecteur(b[1], b[2]);
  const angle = va.angleTo(vb);
  const hauteur = 0.04 + 0.22 * (angle / Math.PI);
  const out: THREE.Vector3[] = [];
  for (let i = 0; i <= segments; i++) {
    const t = i / segments;
    const p = va.clone().multiplyScalar(Math.sin((1 - t) * angle)).add(vb.clone().multiplyScalar(Math.sin(t * angle))).divideScalar(Math.sin(angle));
    out.push(p.multiplyScalar(1.004 + hauteur * Math.sin(Math.PI * t)));
  }
  return out;
}

function texturePoint(): THREE.Texture {
  const c = document.createElement("canvas");
  c.width = c.height = 64;
  const g = c.getContext("2d")!;
  const d = g.createRadialGradient(32, 32, 0, 32, 32, 32);
  d.addColorStop(0, "rgba(255,255,255,1)");
  d.addColorStop(0.45, "rgba(255,255,255,1)");
  d.addColorStop(0.55, "rgba(255,255,255,0.35)");
  d.addColorStop(1, "rgba(255,255,255,0)");
  g.fillStyle = d;
  g.fillRect(0, 0, 64, 64);
  return new THREE.CanvasTexture(c);
}

export default function Globe({ className = "" }: { className?: string }) {
  const boite = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = boite.current;
    if (!el) return;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "low-power" });
    } catch {
      return;                                       // pas de WebGL : la page reste lisible sans le globe
    }
    const calme = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.75));
    el.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(32, 1, 0.1, 20);
    camera.position.set(0, 0, 4.3);
    const monde = new THREE.Group();
    monde.rotation.x = 0.62;                        // inclinaison : l'hémisphère nord, où sont les sites, face à nous
    monde.rotation.y = -(30 + 90) * RAD;            // départ centré entre l'Europe et l'Inde
    scene.add(monde);
    const point = texturePoint();
    const jetables: { dispose: () => void }[] = [point];

    // sphère pleine : masque les points de la face cachée
    const sphereGeo = new THREE.SphereGeometry(0.995, 64, 48);
    const sphereMat = new THREE.MeshBasicMaterial({ color: "#0B2C31" });
    monde.add(new THREE.Mesh(sphereGeo, sphereMat));
    jetables.push(sphereGeo, sphereMat);

    // halo d'atmosphère (effet de bord, sans texture)
    const haloGeo = new THREE.SphereGeometry(1.12, 64, 48);
    const haloMat = new THREE.ShaderMaterial({
      side: THREE.BackSide, transparent: true, depthWrite: false,
      vertexShader: "varying vec3 vN; void main(){ vN = normalize(normalMatrix * normal); gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }",
      fragmentShader: "varying vec3 vN; void main(){ float i = pow(max(0.0, 0.62 - dot(vN, vec3(0.0,0.0,1.0))), 2.6); gl_FragColor = vec4(0.30,0.80,0.84,1.0) * i * 0.8; }",
    });
    scene.add(new THREE.Mesh(haloGeo, haloMat));
    jetables.push(haloGeo, haloMat);

    // ciel : quelques centaines d'étoiles fixes, très discrètes
    const etoiles = new Float32Array(600 * 3);
    for (let i = 0; i < 600; i++) {
      const v = new THREE.Vector3(Math.random() - 0.5, Math.random() - 0.5, Math.random() - 0.5).normalize().multiplyScalar(6 + Math.random() * 4);
      v.toArray(etoiles, i * 3);
    }
    const cielGeo = new THREE.BufferGeometry();
    cielGeo.setAttribute("position", new THREE.BufferAttribute(etoiles, 3));
    const cielMat = new THREE.PointsMaterial({ color: "#CFE8EA", size: 0.025, map: point, transparent: true, opacity: 0.45, depthWrite: false });
    scene.add(new THREE.Points(cielGeo, cielMat));
    jetables.push(cielGeo, cielMat);

    // terres
    const terreGeo = new THREE.BufferGeometry();
    terreGeo.setAttribute("position", new THREE.BufferAttribute(pointsTerre(), 3));
    const terreMat = new THREE.PointsMaterial({ color: "#7FD0D6", size: 0.03, map: point, transparent: true, depthWrite: false, opacity: 0.95 });
    monde.add(new THREE.Points(terreGeo, terreMat));
    jetables.push(terreGeo, terreMat);

    // arcs
    const trajets = LIENS.map(([a, b]) => arc(SITES[a], SITES[b]));
    const arcsPos: number[] = [];
    trajets.forEach((t) => t.forEach((p, i) => i > 0 && arcsPos.push(t[i - 1].x, t[i - 1].y, t[i - 1].z, p.x, p.y, p.z)));
    const arcsGeo = new THREE.BufferGeometry();
    arcsGeo.setAttribute("position", new THREE.Float32BufferAttribute(arcsPos, 3));
    const arcsMat = new THREE.LineBasicMaterial({ color: "#BFE9EC", transparent: true, opacity: 0.55, depthWrite: false, blending: THREE.AdditiveBlending });
    monde.add(new THREE.LineSegments(arcsGeo, arcsMat));
    jetables.push(arcsGeo, arcsMat);

    // sites (blanc), usines (plus grandes), fournisseur touché (orange, pulsation)
    const ids = Object.keys(SITES);
    const sitesGeo = new THREE.BufferGeometry();
    sitesGeo.setAttribute("position", new THREE.Float32BufferAttribute(ids.flatMap((k) => versVecteur(SITES[k][1], SITES[k][2], 1.006).toArray()), 3));
    sitesGeo.setAttribute("color", new THREE.Float32BufferAttribute(ids.flatMap((k) => new THREE.Color(k === TOUCHE ? "#FB923C" : "#F8FAFC").toArray()), 3));
    const sitesMat = new THREE.PointsMaterial({ size: 0.065, map: point, vertexColors: true, transparent: true, depthWrite: false });
    monde.add(new THREE.Points(sitesGeo, sitesMat));
    const usinesGeo = new THREE.BufferGeometry();
    usinesGeo.setAttribute("position", new THREE.Float32BufferAttribute([...USINES].flatMap((k) => versVecteur(SITES[k][1], SITES[k][2], 1.008).toArray()), 3));
    const usinesMat = new THREE.PointsMaterial({ size: 0.1, map: point, color: "#FFFFFF", transparent: true, opacity: 0.9, depthWrite: false });
    monde.add(new THREE.Points(usinesGeo, usinesMat));
    const alerteGeo = new THREE.BufferGeometry();
    alerteGeo.setAttribute("position", new THREE.Float32BufferAttribute(versVecteur(SITES[TOUCHE][1], SITES[TOUCHE][2], 1.008).toArray(), 3));
    const alerteMat = new THREE.PointsMaterial({ size: 0.16, map: point, color: "#FB923C", transparent: true, opacity: 0.4, depthWrite: false });
    monde.add(new THREE.Points(alerteGeo, alerteMat));
    jetables.push(sitesGeo, sitesMat, usinesGeo, usinesMat, alerteGeo, alerteMat);

    // signaux qui circulent : un par arc, vitesse et couleur propres
    // chaque signal laisse une courte traînée : 4 points de plus en plus pâles derrière lui
    const TRAINEE = 4;
    const n = trajets.length * TRAINEE;
    const signauxPos = new Float32Array(n * 3);
    const signauxGeo = new THREE.BufferGeometry();
    signauxGeo.setAttribute("position", new THREE.BufferAttribute(signauxPos, 3));
    signauxGeo.setAttribute("color", new THREE.Float32BufferAttribute(trajets.flatMap((_, i) =>
      Array.from({ length: TRAINEE }, (_, k) => new THREE.Color(SIGNAUX[i % 3]).multiplyScalar(1 - k / TRAINEE).toArray()).flat()), 3));
    const signauxMat = new THREE.PointsMaterial({ size: 0.075, map: point, vertexColors: true, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending });
    monde.add(new THREE.Points(signauxGeo, signauxMat));
    jetables.push(signauxGeo, signauxMat);
    const vitesses = trajets.map((_, i) => 0.07 + 0.04 * ((i * 7) % 5) / 5);
    const phases = trajets.map((_, i) => (i * 0.37) % 1);

    const placerSignaux = (temps: number) => {
      trajets.forEach((t, i) => {
        for (let q = 0; q < TRAINEE; q++) {
          const u = calme ? 0.5 : (((phases[i] + temps * vitesses[i] - q * 0.012) % 1) + 1) % 1;
          const f = u * (t.length - 1);
          const k = Math.floor(f);
          t[k].clone().lerp(t[Math.min(k + 1, t.length - 1)], f - k).toArray(signauxPos, (i * TRAINEE + q) * 3);
        }
      });
      signauxGeo.attributes.position.needsUpdate = true;
    };

    const taille = () => {
      const w = el.clientWidth, h = el.clientHeight;
      if (!w || !h) return;
      renderer.setSize(w, h, false);
      renderer.domElement.style.width = "100%";
      renderer.domElement.style.height = "100%";
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      if (calme) renderer.render(scene, camera);    // image fixe : on la redessine seulement si la taille change
    };
    taille();
    const obsTaille = new ResizeObserver(taille);
    obsTaille.observe(el);

    let visible = true, image = 0, precedent = performance.now(), temps = 0;
    const boucle = (maintenant: number) => {
      image = requestAnimationFrame(boucle);
      const dt = Math.max(0, Math.min(0.05, (maintenant - precedent) / 1000));   // horodatage rAF parfois antérieur
      precedent = maintenant;
      if (!visible || document.hidden) return;
      temps += dt;
      monde.rotation.y += dt * 0.06;               // un tour en un peu plus d'1 min 40 : perceptible, jamais vertigineux
      alerteMat.opacity = 0.25 + 0.25 * (1 + Math.sin(temps * 2.2)) / 2;
      placerSignaux(temps);
      renderer.render(scene, camera);
    };
    const obsVue = new IntersectionObserver(([e]) => { visible = e.isIntersecting; }, { threshold: 0 });
    obsVue.observe(el);

    if (calme) {
      placerSignaux(0);
      renderer.render(scene, camera);
    } else {
      image = requestAnimationFrame(boucle);
    }

    return () => {
      cancelAnimationFrame(image);
      obsTaille.disconnect();
      obsVue.disconnect();
      jetables.forEach((j) => j.dispose());
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, []);

  return <div ref={boite} className={className} aria-hidden />;
}
