// Svelte action: keep multiple horizontal scrollers in lockstep smoothly.
//
// All elements using `use:scrollSync={group}` share one scrollLeft. To stay
// smooth on mobile momentum scrolling, only the element the user is actively
// touching/driving broadcasts its position; followers are updated but do NOT
// re-broadcast (an `applying` flag suppresses the feedback loop that otherwise
// causes jank as 10+ scrollers fight each other every frame).

const groups = new Map(); // name -> { members:Set, active:HTMLElement|null, applying:boolean }

function getGroup(name) {
  if (!groups.has(name))
    groups.set(name, { members: new Set(), active: null, applying: false });
  return groups.get(name);
}

export function scrollSync(node, name = 'default') {
  const g = getGroup(name);
  g.members.add(node);

  let raf = 0;

  const claim = () => { g.active = node; };

  const onScroll = () => {
    // Ignore scroll events we caused programmatically, and events from
    // followers while another element is the active driver.
    if (g.applying) return;
    if (g.active && g.active !== node) return;
    if (raf) return;
    raf = requestAnimationFrame(() => {
      raf = 0;
      const x = node.scrollLeft;
      g.applying = true;
      for (const other of g.members) {
        if (other !== node && other.scrollLeft !== x) other.scrollLeft = x;
      }
      g.applying = false;
    });
  };

  // Whoever the user touches/points at becomes the driver.
  const onPointerDown = () => claim();
  const onTouchStart = () => claim();

  node.addEventListener('scroll', onScroll, { passive: true });
  node.addEventListener('pointerdown', onPointerDown, { passive: true });
  node.addEventListener('touchstart', onTouchStart, { passive: true });

  // Desktop: translate vertical wheel into horizontal scroll (only on overflow,
  // only when the gesture is mostly vertical so trackpad h-scroll still works).
  const onWheel = (e) => {
    if (node.scrollWidth <= node.clientWidth) return;
    if (Math.abs(e.deltaY) > Math.abs(e.deltaX)) {
      claim();
      node.scrollLeft += e.deltaY;
      e.preventDefault();
    }
  };
  node.addEventListener('wheel', onWheel, { passive: false });

  return {
    destroy() {
      node.removeEventListener('scroll', onScroll);
      node.removeEventListener('pointerdown', onPointerDown);
      node.removeEventListener('touchstart', onTouchStart);
      node.removeEventListener('wheel', onWheel);
      g.members.delete(node);
      if (g.active === node) g.active = null;
      if (g.members.size === 0) groups.delete(name);
    }
  };
}
