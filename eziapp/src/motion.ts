/**
 * 动效工具：对齐 app/motion.py。
 *
 * 开关只认应用内 ui_motion，不跟随系统 prefers-reduced-motion——那个标志
 * 常被系统优化或远程会话静默关掉，跟随它的结果是用户侧动效全部消失。
 */

export const EASE_OUT = (t: number) => 1 - Math.pow(1 - t, 3);
export const EASE_IN_OUT = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
export const EASE_BACK = (t: number) => {
  const c = 1.70158 + 1;
  return 1 + (c + 1) * Math.pow(t - 1, 3) + c * Math.pow(t - 1, 2);
};

export function motionOk(): boolean {
  return document.documentElement.dataset.motion !== 'off';
}

/** 数值补间：setter(v) 按帧调用。关动效时直接落终值。 */
export function tween(
  setter: (value: number) => void,
  from: number,
  to: number,
  ms = 240,
  easing: (t: number) => number = EASE_OUT,
): () => void {
  if (!motionOk() || from === to || ms <= 0) {
    setter(to);
    return () => undefined;
  }
  let frame = 0;
  const t0 = performance.now();
  const step = (now: number) => {
    const raw = Math.min(1, (now - t0) / ms);
    setter(from + (to - from) * easing(raw));
    if (raw < 1) frame = requestAnimationFrame(step);
  };
  frame = requestAnimationFrame(step);
  return () => cancelAnimationFrame(frame);
}

/** 数字滚动：把元素文本从当前值补间到目标值。 */
export function countUp(el: HTMLElement | null, to: number, format: (v: number) => string, ms = 620) {
  if (!el) return;
  const from = Number(el.dataset.value || 0);
  el.dataset.value = String(to);
  tween((v) => { el.textContent = format(v); }, from, to, ms);
}

/**
 * 进度条推进。宽度的缓动交给 CSS 的 `transition: width`——以前这里还额外跑一个
 * rAF 补间逐帧写 width，等于让 CSS 去追一个每帧都在变的目标，进度条既永远滞后
 * 又白烧一个循环。这里只写终值，外加完成时闪一下。
 */
export function smoothProgress(fill: HTMLElement | null, percent: number, succeeded = false) {
  if (!fill) return;
  const target = Math.max(0, Math.min(100, percent));
  // 没有 data-pct 时取到 NaN，比较为假，于是第一次一定会写——CSS 那边靠
  // [data-pct="100"] 停掉流光，这个属性缺了就一直转。
  const previous = Number(fill.dataset.pct ?? NaN);
  if (!(Math.abs(target - previous) < 0.25)) {
    fill.dataset.pct = String(target);
    fill.style.width = `${target}%`;
  }
  if (succeeded && fill.dataset.flashed !== '1') {
    fill.dataset.flashed = '1';
    if (motionOk()) {
      fill.classList.add('progress-done');
      fill.addEventListener('animationend', () => fill.classList.remove('progress-done'), { once: true });
    }
  }
}

/** 缩放脉冲：角标计数变化。上一发没放完就跳过，避免连成抖动。 */
export function pop(el: HTMLElement | null) {
  if (!el || !motionOk() || el.dataset.popping === '1') return;
  el.dataset.popping = '1';
  el.classList.remove('anim-pop');
  void el.offsetWidth;
  el.classList.add('anim-pop');
  setTimeout(() => {
    el.classList.remove('anim-pop');
    delete el.dataset.popping;
  }, 320);
}

type ViewTransitionDoc = Document & {
  startViewTransition?: (cb: () => void | Promise<void>) => { finished: Promise<void> };
};

/**
 * 换页转场。
 *
 * 调用方要先把页面模块 await 好再进来：以前是「淡出 90ms → 才开始 import() 该页
 * chunk」，两段等待串在一起，首次进一个页面能空出小半秒。
 *
 * 浏览器支持 View Transitions 就交给它——新旧两帧由合成器直接交叉，比先清空
 * 再重画少一次白屏。不支持时退回原来的淡出淡入。
 */
export async function pageSwap(host: HTMLElement, render: () => void) {
  if (!motionOk()) {
    render();
    return;
  }
  const startViewTransition = (document as ViewTransitionDoc).startViewTransition;
  if (startViewTransition) {
    let painted = false;
    const paint = () => { painted = true; render(); };
    try {
      await startViewTransition.call(document, paint).finished;
    } catch {
      // 转场被打断（连点侧栏）时内容已经画上去了；但要是它压根没走到回调，
      // 这里得补一次，否则就是一片空白。
      if (!painted) paint();
    }
    return;
  }
  host.classList.add('page-leave');
  await new Promise((resolve) => setTimeout(resolve, 90));
  host.classList.remove('page-leave');
  render();
  host.classList.remove('page-enter');
  void host.offsetWidth;
  host.classList.add('page-enter');
}

/**
 * 点击涟漪：全局委托，作用于所有按钮。
 *
 * 四个目标选择器在 CSS 里都已经是 `position: relative`，所以不必再
 * getComputedStyle 探一次——那一下会在点击路径上强制一次样式重算。
 */
export function installRipple(root: HTMLElement) {
  root.addEventListener('pointerdown', (event) => {
    if (!motionOk() || event.button !== 0) return;
    const target = (event.target as HTMLElement | null)?.closest<HTMLElement>('.btn, .tab, .nav-item, .quick-btn');
    if (!target || target.hasAttribute('disabled')) return;
    const rect = target.getBoundingClientRect();
    const size = Math.max(rect.width, rect.height) * 1.6;
    const ripple = document.createElement('span');
    ripple.className = 'ripple';
    ripple.style.width = ripple.style.height = `${size}px`;
    ripple.style.left = `${event.clientX - rect.left - size / 2}px`;
    ripple.style.top = `${event.clientY - rect.top - size / 2}px`;
    ripple.addEventListener('animationend', () => ripple.remove(), { once: true });
    target.appendChild(ripple);
  }, { passive: true });
}
