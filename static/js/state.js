let _season = null;
const _listeners = {};

export function getSeason() { return _season; }

export function setSeason(s) {
  if (_season === s) return;
  _season = s;
  (_listeners.season || []).forEach(fn => fn(s));
}

export function on(event, fn) {
  (_listeners[event] ??= []).push(fn);
}
