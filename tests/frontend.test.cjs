const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const code = fs.readFileSync(path.join(__dirname, '../assets/frontend.js'), 'utf8');

function fixture(options = {}) {
    const observers = [];
    const listeners = {};
    function video() {
        const attributes = new Map([['controls', '']]);
        const events = {};
        return {
            paused: true, muted: false, volume: 1, controls: true, playCalls: 0,
            setAttribute: (name, value) => attributes.set(name, value),
            removeAttribute: name => attributes.delete(name),
            hasAttribute: name => attributes.has(name),
            addEventListener: (name, callback) => { (events[name] ||= []).push(callback); },
            fire(name, event = {}) { (events[name] || []).forEach(callback => callback(event)); },
            play() {
                this.playCalls++;
                if (options.reject) return Promise.reject(new Error('Autoplay blocked'));
                this.paused = false;
                return Promise.resolve();
            }
        };
    }
    const target = video();
    const unrelated = video();
    const videos = [target];
    const document = {
        readyState: options.loading ? 'loading' : 'complete',
        hidden: options.hidden || false,
        body: {},
        querySelectorAll(selector) {
            assert.equal(selector, '.playmac-steam-about video');
            return videos;
        },
        addEventListener(name, callback) { listeners[name] = callback; }
    };
    class MutationObserver {
        constructor(callback) { this.callback = callback; observers.push(this); }
        observe(target, options) { this.target = target; this.options = options; }
    }
    vm.runInNewContext(code, { document, MutationObserver, WeakSet });
    return {target, unrelated, video, videos, document, listeners, observers};
}

function check(video) {
    assert.equal(video.defaultMuted, true);
    assert.equal(video.muted, true);
    assert.equal(video.volume, 0);
    assert.equal(video.autoplay, true);
    assert.equal(video.playsInline, true);
    assert.equal(video.controls, false);
    assert.equal(video.hasAttribute('controls'), false);
    for (const attr of ['muted', 'autoplay', 'playsinline', 'disablepictureinpicture', 'disableremoteplayback']) {
        assert.equal(video.hasAttribute(attr), true, attr);
    }
}

test('Steam videos start muted without controls, with right-click blocked; others unchanged', () => {
    const f = fixture();
    check(f.target);
    assert.equal(f.target.playCalls, 1);
    let prevented = false;
    f.target.fire('contextmenu', {preventDefault() { prevented = true; }});
    assert.equal(prevented, true);
    assert.equal(f.unrelated.muted, false);
    assert.equal(f.unrelated.controls, true);
    assert.equal(f.unrelated.playCalls, 0);
});

test('unmute and theme-added controls are reverted', () => {
    const f = fixture();
    f.target.muted = false;
    f.target.volume = 0.5;
    f.target.fire('volumechange');
    check(f.target);
    f.target.controls = true;
    f.target.setAttribute('controls', '');
    f.target.autoplay = false;
    f.observers.find(observer => observer.target === f.target).callback();
    check(f.target);
});

test('dynamically inserted video is initialized once', () => {
    const f = fixture();
    const added = f.video();
    f.videos.push(added);
    const observer = f.observers.find(observer => observer.target === f.document.body);
    observer.callback();
    observer.callback();
    check(added);
    assert.equal(added.playCalls, 1);
});

test('hidden page waits, then retries when visible or metadata arrives', () => {
    const f = fixture({hidden: true});
    assert.equal(f.target.playCalls, 0);
    f.document.hidden = false;
    f.listeners.visibilitychange();
    assert.equal(f.target.playCalls, 1);
    f.target.paused = true;
    f.target.fire('loadedmetadata');
    assert.equal(f.target.playCalls, 2);
});

test('browser autoplay rejection is handled and DOM ready is respected', async () => {
    const f = fixture({reject: true, loading: true});
    assert.equal(f.target.playCalls, 0);
    f.listeners.DOMContentLoaded();
    check(f.target);
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(f.target.playCalls, 1);
});
