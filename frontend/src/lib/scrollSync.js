// Svelte action: keep multiple horizontal scrollers in lockstep, and make them
// scrollable on desktop (mouse wheels only scroll vertically by default).
//
// All elements using `use:scrollSync={group}` with the same group name share
// one scrollLeft — scrolling any (day header or any spot row) moves all, like
// Surfline's calendar. rAF-throttled to avoid feedback loops.

const groups = new Map(); // name -> Set<HTMLElement>

export function scrollSync(node, group = 'default') {
  if (!groups.has(group)) groups.set(group, new Set());
  const members = groups.get(group);
  members.add(node);

  let raf = 0;
  const onScroll = () => {
    if (raf) return;
    raf = requestAnimationFrame(() => {
      raf = 0;
      const x = node.scrollLeft;
      for (const other of members) {
        if (other !== node && other.scrollLeft !== x) other.scrollLeft = x;
      }
    });
  };

  // Desktop: translate vertical wheel into horizontal scroll so a mouse can
  // move the calendar. Only when there's actually horizontal overflow, and
  // when the gesture is predominantly vertical (leave trackpad h-scroll alone).
  const onWheel = (e) => {
    const overflow = node.scrollWidth > node.clientWidth;
    if (!overflow) return;
    if (Math.abs(e.deltaY) > Math.abs(e.deltaX)) {
      node.scrollLeft += e.deltaY;
      e.preventDefault();
    }
  };

  node.addEventListener('scroll', onScroll, { passive: true });
  node.addEventListener('wheel', onWheel, { passive: false });

  return {
    destroy() {
      node.removeEventListener('scroll', onScroll);
      node.removeEventListener('wheel', onWheel);
      members.delete(node);
      if (members.size === 0) groups.delete(group);
    }
  };
}
