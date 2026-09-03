(function () {
    'use strict';

    var selector = '.playmac-steam-about video';
    var ready = new WeakSet();

    function enforce(video) {
        video.defaultMuted = true;
        video.muted = true;
        video.volume = 0;
        video.autoplay = true;
        video.playsInline = true;
        video.controls = false;
        video.removeAttribute('controls');
        video.setAttribute('muted', '');
        video.setAttribute('autoplay', '');
        video.setAttribute('playsinline', '');
        video.setAttribute('disablepictureinpicture', '');
        video.setAttribute('disableremoteplayback', '');
        video.setAttribute('controlslist', 'nodownload nofullscreen noremoteplayback');
    }

    function play(video) {
        enforce(video);
        if (document.hidden || !video.paused) return;
        var pending = video.play();
        // Autoplay can still be blocked by browser power-saving/user policy.
        if (pending && pending.catch) pending.catch(function () {});
    }

    function init(video) {
        if (ready.has(video)) return;
        ready.add(video);
        enforce(video);
        video.addEventListener('contextmenu', function (event) {
            event.preventDefault();
        });
        video.addEventListener('volumechange', function () {
            if (!video.muted || video.volume !== 0) enforce(video);
        });
        video.addEventListener('loadedmetadata', function () { play(video); });
        video.addEventListener('canplay', function () { play(video); });
        new MutationObserver(function () {
            if (video.hasAttribute('controls') || video.controls || !video.muted || !video.autoplay || !video.playsInline) {
                enforce(video);
            }
        }).observe(video, {attributes: true, attributeFilter: ['controls', 'muted', 'autoplay', 'playsinline']});
        play(video);
    }

    function scan() { document.querySelectorAll(selector).forEach(init); }
    function start() {
        scan();
        new MutationObserver(scan).observe(document.body, {childList: true, subtree: true});
        document.addEventListener('visibilitychange', function () {
            if (!document.hidden) document.querySelectorAll(selector).forEach(play);
        });
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
    else start();
})();
