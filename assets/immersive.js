/*
  Immersive fullscreen viewing mode for lightGallery 1.2.14.
  Hand-authored; injected into every generated page by patchHtml.py.

  Registers as a lightGallery *module*: the core constructs every entry of
  $.fn.lightGallery.modules in Plugin.build() (lightgallery.js:206-209) and calls
  .destroy() on each in Plugin.destroy() (:1252-1257), so the open/close lifecycle
  comes for free.

  Deliberately does NOT wrap $.fn.lightGallery itself. Wrapping it means
  re-attaching .modules to the same object, and getting that wrong silently kills
  the EXIF panel, the pager and autoplay. Options that structure() consumes before
  modules exist (s.controls, s.addClass) are handled in assets/immersive.css instead.

  index.html has an empty #media, so Plugin.build() never runs there and this
  module is never constructed -- no guard needed.
*/
(function ($, window, document) {
  'use strict';

  if (!$ || !$.fn || !$.fn.lightGallery) { return; }

  var CFG = {
    // ms of stillness before the chrome fades. Floor is ~1000: lg-thumbnail slides
    // the strip in at 700ms after open (lg-thumbnail.js:60-69) and the slide takes
    // 250ms, so below that the fade would start while the filmstrip is still
    // arriving. That auto-open cannot be cancelled -- its setTimeout handle is not
    // stored, and showThumbByDefault has already been read by the time this
    // module's constructor runs.
    hideBars: 2500,
    maxScale: 3,      // hard zoom ceiling
    overzoom: 2,      // ... but at most 2x past the derivative's own pixels
    minCeiling: 2,    // ... and never cap below 2x
    dblScale: 2.5,    // double-tap / double-click target
    tapMs: 300,       // double-tap window
    tapSlop: 30,      // px allowed between the two taps
    moveSlop: 10,     // px that turns a tap into a drag
    wheelMs: 250      // one slide per wheel gesture, not five
  };

  var abs = Math.abs;
  var min = Math.min;
  var max = Math.max;

  function noop() {}

  function dist(a, b) {
    var x = a.clientX - b.clientX;
    var y = a.clientY - b.clientY;
    return Math.sqrt(x * x + y * y) || 1;
  }

  function centre(p) {
    if (p.length > 1) {
      return { x: (p[0].clientX + p[1].clientX) / 2, y: (p[0].clientY + p[1].clientY) / 2 };
    }
    return { x: p[0].clientX, y: p[0].clientY };
  }

  // e.touches, never e.targetTouches: with one finger on the <img> and one on the
  // letterbox, targetTouches.length reads 1. That is exactly why the shipped
  // lg-zoom.js cannot see a pinch at all.
  function touchList(e) {
    var out = [];
    var t = e.touches;
    var i;
    for (i = 0; t && i < t.length; i++) { out.push(t[i]); }
    return out;
  }

  /* --- fullscreen API ---------------------------------------------------- */

  var docEl = document.documentElement;
  var fsRequest = docEl.requestFullscreen || docEl.webkitRequestFullscreen ||
                  docEl.mozRequestFullScreen || docEl.msRequestFullscreen;
  var fsRelease = document.exitFullscreen || document.webkitExitFullscreen ||
                  document.mozCancelFullScreen || document.msExitFullscreen;

  function fsNode() {
    return document.fullscreenElement || document.webkitFullscreenElement ||
           document.mozFullScreenElement || document.msFullscreenElement || null;
  }

  function fsEnter() {
    if (!fsRequest) { return; }
    try {
      var p = fsRequest.call(docEl);
      if (p && p['catch']) { p['catch'](noop); }
    } catch (err) { /* user gesture lost, or blocked by permissions policy */ }
  }

  function fsExit() {
    if (!fsRelease || !fsNode()) { return; }
    try {
      var p = fsRelease.call(document);
      if (p && p['catch']) { p['catch'](noop); }
    } catch (err) { /* already leaving */ }
  }

  /* ====================================================================== */

  function Immersive(element) {
    // Must exist before any early return: core.destroy() calls us regardless.
    this.listeners = [];
    this.core = $(element).data('lightGallery');
    if (!this.core || !this.core.$outer || !this.core.$outer.length) { return this; }

    // hideBarsDelay is read lazily inside the auto-hide timer callback
    // (lightgallery.js:246-248), and module constructors run at :207 -- before
    // that handler is even registered at :239. So patching `s` here is enough,
    // and we never have to touch the init call baked into the generated HTML.
    this.core.s.hideBarsDelay = CFG.hideBars;

    this.scale = 1;
    this.tx = 0;
    this.ty = 0;
    this.base = null;
    this.gesture = null;   // 'touch' | 'mouse' while one of ours is running
    this.stole = false;    // we swallowed events lightGallery was expecting
    this.lastTap = 0;
    this.tapX = 0;
    this.tapY = 0;
    this.wheelAt = 0;

    this.init();
    return this;
  }

  // Capture phase, non-passive. jQuery 1.11 registers lightGallery's
  // touchstart/touchmove/touchend on each .lg-item in the bubble phase
  // (lightgallery.js:1055-1081), and DOM dispatch visits capture listeners on
  // every ancestor before the target -- so a capture listener on their ancestor
  // always runs first, and stopPropagation() ends the rest of the dispatch.
  // On engines too old for the options object, {…} coerces to true = capture,
  // and passive defaults to false there anyway. Still correct.
  Immersive.prototype.on = function (el, type, fn) {
    if (!el) { return; }
    el.addEventListener(type, fn, { passive: false, capture: true });
    this.listeners.push([el, type, fn]);
  };

  Immersive.prototype.init = function () {
    var self = this;
    var core = this.core;

    // .lg-inner holds ONLY the slides. .lg-toolbar / .lg-actions / .lg-sub-html
    // and lg-thumbnail's .lg-thumb-outer are siblings inside .lg, and lg-exif's
    // .lg-exif panel (with the Leaflet map) is a sibling inside .lg-outer -- so
    // binding here cannot swallow their gestures, and needs no target filtering.
    this.inner = core.$outer.find('.lg-inner')[0];
    this.frame = core.$outer.find('.lg')[0];
    if (!this.inner || !this.frame) { return; }

    this.on(this.inner, 'touchstart', function (e) { self.down(e, touchList(e)); });
    this.on(this.inner, 'touchmove', function (e) { self.move(e, touchList(e)); });
    this.on(this.inner, 'touchend', function (e) { self.up(e, touchList(e)); });
    this.on(this.inner, 'touchcancel', function (e) { self.up(e, touchList(e)); });

    // Desktop: dblclick zooms, and while zoomed the mouse pans. move/up live on
    // document so a drag may leave .lg-inner; both are inert unless we own the
    // gesture, and stopPropagation() during a pan is what stops closeGallery's
    // mouseup handler (lightgallery.js:1208) from closing the viewer.
    this.on(this.inner, 'dblclick', function (e) {
      if (!self.wrap()) { return; }
      e.preventDefault();
      e.stopPropagation();
      self.zoomTo(self.zoomed() ? 1 : CFG.dblScale, e.clientX, e.clientY, true);
    });
    this.on(this.inner, 'mousedown', function (e) {
      if (self.zoomed() && self.seed([e], 'mouse')) { self.steal(e); }
    });
    this.on(document, 'mousemove', function (e) {
      if (self.gesture === 'mouse') { self.move(e, [e]); }
    });
    this.on(document, 'mouseup', function (e) {
      if (self.gesture !== 'mouse') { return; }
      self.steal(e);
      self.gesture = null;
      self.settle();
    });

    // Wheel / trackpad navigation. lightGallery has a mousewheel handler but it
    // needs deltaY on the jQuery event, which jQuery 1.11 does not copy across,
    // so it is dead code -- wire it natively instead.
    this.on(this.inner, 'wheel', function (e) { self.wheel(e); });

    // iOS fires its own gesture* events for two-finger pinches and would zoom
    // the *page* (user-scalable=no has been ignored since iOS 10). Bound on .lg,
    // which excludes .lg-exif, so Leaflet keeps its own pinch-zoom.
    var swallow = function (e) { if (e.cancelable) { e.preventDefault(); } };
    this.on(this.frame, 'gesturestart', swallow);
    this.on(this.frame, 'gesturechange', swallow);

    this.initKeys();
    this.initFullscreen();

    // The photo now fills the frame (object-fit), so clicks on the black
    // letterbox land on the <img> and closeGallery's target test
    // (lightgallery.js:1200, :1210) can no longer match .lg-img-wrap. Reinstate
    // click-the-letterbox-to-close ourselves, from the painted rect.
    this.on(this.inner, 'click', function (e) {
      if (self.gesture || self.stole || self.zoomed()) { return; }
      if (self.inLetterbox(e.clientX, e.clientY)) { core.destroy(); }
    });

    // Reset when the frame or the content changes under a live transform.
    core.$el.on('onBeforeSlide.lg.tm.imm', function () { self.reset(); });
    $(window).on('resize.imm orientationchange.imm', function () { self.reset(); });

    // lightgallery.js:239-250 *registers* the mousemove/click/touchstart reveal
    // handler but never invokes it, so nothing fades until the first pointer
    // event inside .lg-outer -- which on a phone never happens, because the
    // opening tap landed on a grid thumbnail before .lg-outer existed.
    //
    // Arming it in this constructor is too early: slide() runs at :212, right
    // after the module ctors at :207, and clears hideBartimeout at :767. Every
    // later slide change clears it again and only a pointer event re-arms it, so
    // after keyboard or wheel navigation the chrome would stay up forever. Arm
    // on both events that fire after that clearTimeout instead.
    core.$el.on('onAfterOpen.lg.tm.imm onAfterSlide.lg.tm.imm', function () {
      self.armHideBars();
    });

    // Swiping between photos kept popping the toolbar back: the reveal handler at
    // lightgallery.js:239 listens for `mousemove.lg click.lg touchstart.lg` on
    // .lg-outer, and a swipe *starts* with a touchstart. Drop only that one type.
    // mousemove and click survive, so desktop and keyboard users are unaffected;
    // on touch neither of those fires (lightGallery's swipe handlers preventDefault,
    // which suppresses the compatibility mouse events), so on a phone the reveal
    // becomes exclusively ours, via tap -- see up().
    //
    // Deferred by design. Module constructors run at lightgallery.js:207 and
    // onAfterOpen.lg is triggered at :236, but the handler is not bound until :239
    // -- so calling .off() from either hook would silently do nothing. build()
    // runs straight through without yielding, so a 0ms timeout lands just after it.
    //
    // Verified safe: nothing else in the loaded set binds touchstart with the .lg
    // namespace directly on .lg-outer, and there are no delegated handlers. jQuery
    // .off() on $outer cannot reach descendants, so lightGallery's touchstart.lg on
    // .lg-item and lg-thumbnail's on .lg-thumb both survive.
    this.offTimer = setTimeout(function () {
      core.$outer.off('touchstart.lg');
    }, 0);
  };

  /* --- chrome visibility -------------------------------------------------- */

  // Uses the plugin's own timer slot, so its clearTimeout() still cancels ours.
  Immersive.prototype.armHideBars = function () {
    var core = this.core;
    clearTimeout(core.hideBartimeout);
    core.hideBartimeout = setTimeout(function () {
      core.$outer.addClass('lg-hide-items');
    }, core.s.hideBarsDelay);
  };

  Immersive.prototype.showBars = function () {
    this.core.$outer.removeClass('lg-hide-items');
    this.armHideBars();
  };

  Immersive.prototype.hideBars = function () {
    clearTimeout(this.core.hideBartimeout);
    this.core.$outer.addClass('lg-hide-items');
  };

  Immersive.prototype.toggleBars = function () {
    if (this.core.$outer.hasClass('lg-hide-items')) { this.showBars(); } else { this.hideBars(); }
  };

  /* --- geometry ---------------------------------------------------------- */

  // .lg-img-wrap exists for image slides only, so video slides keep
  // lightGallery's swipe and video.js' own touch handling untouched.
  Immersive.prototype.wrap = function () {
    return this.core.$outer.find('.lg-item.lg-current .lg-img-wrap')[0] || null;
  };

  Immersive.prototype.zoomed = function () {
    return this.scale > 1.01;
  };

  // Measure the *untransformed* image box and the frame, both in client coords.
  // We know our own transform exactly (rect = scale*base + translate), so `base`
  // is derived from the live rect rather than cached -- which makes this immune
  // to late-loading images, resize, rotation and fullscreen transitions.
  Immersive.prototype.measure = function () {
    var wrap = this.wrap();
    var img = wrap && wrap.querySelector('.lg-image');
    if (!img) { return false; }

    // Measure the WRAP, not the <img>. immersive.css sizes the image to the full
    // wrap, but the <img> also carries lightGallery's own lg-start-zoom
    // transform -- scale3d(.5,.5,.5) until .lg-item gains lg-complete
    // (lightgallery.css:244-261) -- which would corrupt `base`, since our model
    // assumes the only transform in play is the one we wrote on the wrap.
    var box = wrap.getBoundingClientRect();
    if (!box.width || !box.height) { return false; }

    // The image is object-fit:contain across that box, so the photo is
    // letterboxed inside it. Reproduce contain's own arithmetic to get the
    // painted rect: everything downstream (clamp, anchor, letterbox
    // hit-testing) is about the photo, not the box. Our scaling is uniform, so
    // it carries through to the painted rect unchanged.
    var r = box;
    var nw = img.naturalWidth;
    var nh = img.naturalHeight;
    if (nw && nh) {
      var k = min(box.width / nw, box.height / nh);
      var pw = nw * k;
      var ph = nh * k;
      r = {
        left: box.left + (box.width - pw) / 2,
        top: box.top + (box.height - ph) / 2,
        width: pw,
        height: ph
      };
    }

    var s = this.scale;
    var f = this.frame.getBoundingClientRect();

    this.base = {
      x: (r.left - this.tx) / s,
      y: (r.top - this.ty) / s,
      w: r.width / s,
      h: r.height / s
    };
    this.view = { x: f.left, y: f.top, w: f.width, h: f.height };

    // media/large/** is capped at 1000px height, so cap the zoom by how much
    // real detail this derivative actually has rather than a blanket 3x.
    var natural = nw || this.base.w;
    this.ceiling = min(CFG.maxScale,
                       max(CFG.minCeiling, (natural / this.base.w) * CFG.overzoom));
    return true;
  };

  // True when (x, y) lies in the black letterbox rather than on the photo.
  Immersive.prototype.inLetterbox = function (x, y) {
    if (!this.measure()) { return false; }
    var s = this.scale;
    var b = this.base;
    var l = b.x * s + this.tx;
    var t = b.y * s + this.ty;
    return x < l || x > l + b.w * s || y < t || y > t + b.h * s;
  };

  // Cover the frame while the image overflows it; otherwise hold the image
  // exactly where the CSS centring put it -- so translate is 0 at scale 1 and
  // handing control back to lightGallery can never jump.
  Immersive.prototype.axis = function (s, t, bMin, bLen, vMin, vLen) {
    if (bLen * s > vLen + 0.5) {
      return max(vMin + vLen - (bMin + bLen) * s, min(vMin - bMin * s, t));
    }
    return (1 - s) * (bMin + bLen / 2);
  };

  Immersive.prototype.apply = function (animate) {
    var wrap = this.wrap();
    var b = this.base;
    var v = this.view;
    if (!wrap || !b) { return; }

    this.tx = this.axis(this.scale, this.tx, b.x, b.w, v.x, v.w);
    this.ty = this.axis(this.scale, this.ty, b.y, b.h, v.y, v.h);

    $(wrap)
      .toggleClass('imm-anim', !!animate)
      .css('transform', 'translate3d(' + this.tx + 'px,' + this.ty + 'px,0) scale(' + this.scale + ')');

    // lg-zoomed is lightGallery's own "suspend swipe and drag" flag: every touch
    // and mouse handler it installs is gated on it (:1056, :1064, :1073, :1095).
    this.core.$outer.toggleClass('lg-zoomed', this.zoomed());
  };

  /* --- gestures ---------------------------------------------------------- */

  Immersive.prototype.seed = function (points, kind) {
    if (!points.length || !this.measure()) { return false; }
    this.gesture = kind;
    this.s0 = this.scale;
    this.t0 = { x: this.tx, y: this.ty };
    this.m0 = centre(points);
    this.d0 = points.length > 1 ? dist(points[0], points[1]) : 0;
    this.core.$outer.addClass('imm-active');
    return true;
  };

  // Take the event away from lightGallery, and clean up the swipe it may already
  // have started: its touchstart fires on the FIRST finger, so by the time the
  // second lands it may have put inline transforms on the slides and lg-dragging
  // on .lg-outer. Its touchmove/touchend are gated on !lg-zoomed and now bail
  // *before* their own cleanup, so we do what its touchEnd() does (:1024, :1035).
  Immersive.prototype.steal = function (e) {
    if (e.cancelable) { e.preventDefault(); }
    e.stopPropagation();
    if (this.stole) { return; }
    this.stole = true;
    this.core.$outer.removeClass('lg-dragging');
    this.core.$slide.removeAttr('style');
  };

  Immersive.prototype.down = function (e, points) {
    if (points.length === 1) {
      this.tapable = true;
      this.downAt = new Date().getTime();
      this.moved = false;
      this.downX = points[0].clientX;
      this.downY = points[0].clientY;
    } else {
      this.tapable = false;
    }
    // Two fingers always mean pinch; one finger only pans when already zoomed.
    // Otherwise: hands off, and lightGallery swipes as it always did.
    if ((points.length > 1 || this.zoomed()) && this.seed(points, 'touch')) {
      this.steal(e);
    }
  };

  Immersive.prototype.move = function (e, points) {
    if (!points.length) { return; }

    // Track movement even when we do NOT own the gesture -- this has to happen
    // before the ownership check below. On a plain one-finger swipe the module
    // stays out of the way, so an early return here left `moved` false and up()
    // then read a fast flick (<250ms) as a tap: two quick swipes could fire the
    // double-tap zoom, and tap-to-toggle would flip the chrome on every flick.
    if (this.tapable &&
        (abs(points[0].clientX - this.downX) > CFG.moveSlop ||
         abs(points[0].clientY - this.downY) > CFG.moveSlop)) {
      this.moved = true;
    }

    if (!this.gesture) { return; }
    this.steal(e);

    // Finger count changed mid-gesture: re-seed from the new configuration
    // rather than reading a stale baseline distance.
    if ((points.length > 1) !== (this.d0 > 0)) { this.seed(points, this.gesture); return; }

    var s = this.d0
      ? min(this.ceiling, max(1, this.s0 * dist(points[0], points[1]) / this.d0))
      : this.s0;
    var m = centre(points);
    var k = s / this.s0;

    this.scale = s;
    // Pin the image point that was under the gesture centre to the current
    // centre: t = m - k * (m0 - t0). With k === 1 this is a plain drag.
    this.tx = m.x - k * (this.m0.x - this.t0.x);
    this.ty = m.y - k * (this.m0.y - this.t0.y);
    this.apply(false);
  };

  Immersive.prototype.up = function (e, points) {
    var self = this;
    if (this.gesture) { this.steal(e); }
    if (points.length) {                 // other fingers still down
      if (this.gesture) { this.seed(points, this.gesture); }
      return;
    }

    var now = new Date().getTime();
    var tap = this.tapable && !this.moved && (now - this.downAt) < 250;
    var dbl = tap && (now - this.lastTap) < CFG.tapMs &&
              abs(this.downX - this.tapX) < CFG.tapSlop &&
              abs(this.downY - this.tapY) < CFG.tapSlop;

    this.lastTap = (tap && !dbl) ? now : 0;   // a handled double-tap seeds no triple
    this.tapX = this.downX;
    this.tapY = this.downY;
    this.gesture = null;

    clearTimeout(this.tapTimer);

    if (dbl) {
      this.steal(e);                          // also suppresses onSlideClick.lg
      this.zoomTo(this.zoomed() ? 1 : CFG.dblScale, this.downX, this.downY, true);
    } else if (tap) {
      // A tap toggles the chrome -- the only way back now that touchstart no
      // longer reveals it (see init()). Deferred past the double-tap window so a
      // double-tap zooms without also flipping the chrome; the clearTimeout above
      // is what cancels it when the second tap lands.
      this.tapTimer = setTimeout(function () { self.toggleBars(); }, CFG.tapMs);

      // Suppress the compatibility click. lightGallery normally preventDefaults
      // touchstart for us, but not in two windows: the first ~50ms after open
      // (enableSwipe is bound on a setTimeout, lightgallery.js:222-225) and any
      // single-photo album (it is gated on $items.length > 1). There the synthetic
      // click would both re-reveal via the surviving click.lg handler and hit our
      // letterbox-close. Suppressing it also makes touch uniform: a tap always
      // toggles and never closes, leaving click-the-letterbox-to-close as the
      // desktop affordance it was.
      if (e.cancelable) { e.preventDefault(); }
    }
    this.settle();
  };

  Immersive.prototype.zoomTo = function (s, ax, ay, animate) {
    if (!this.measure()) { return; }
    s = min(this.ceiling, max(1, s));
    var k = s / this.scale;
    this.tx = ax - k * (ax - this.tx);        // keep (ax, ay) fixed on screen
    this.ty = ay - k * (ay - this.ty);
    this.scale = s;
    this.apply(animate);
  };

  Immersive.prototype.settle = function () {
    this.core.$outer.removeClass('imm-active');   // drop will-change so the
    if (!this.zoomed()) {                         // engine re-rasterises sharp
      if (this.tx || this.ty || this.scale !== 1) {
        this.scale = 1;
        this.tx = 0;
        this.ty = 0;
        this.apply(true);                         // animate the snap back to fit
      }
      this.core.$outer.removeClass('lg-zoomed');
    }
    if (this.stole) { this.stole = false; this.releaseSwipe(); }
  };

  // lightGallery keeps startCoords / endCoords / isMoved inside the enableSwipe
  // closure (lightgallery.js:1049-1051) with no accessor. If we hijacked a
  // gesture after its touchstart had run, isMoved stays true and endCoords stale,
  // so a later innocent single tap is read as a >swipeThreshold swipe and jumps a
  // slide. Rebinding through the library's own method gives it a fresh closure.
  Immersive.prototype.releaseSwipe = function () {
    if (this.core.$items.length < 2) { return; }   // the core never bound them
    this.core.$slide.off('touchstart.lg touchmove.lg touchend.lg');
    this.core.enableSwipe();
  };

  Immersive.prototype.reset = function () {
    clearTimeout(this.tapTimer);
    this.gesture = null;
    this.scale = 1;
    this.tx = 0;
    this.ty = 0;
    this.base = null;
    this.core.$outer.removeClass('lg-zoomed imm-active');
    this.core.$slide.find('.lg-img-wrap').removeClass('imm-anim').css('transform', '');
    if (this.stole) { this.stole = false; this.releaseSwipe(); }
  };

  /* --- wheel / trackpad navigation --------------------------------------- */

  Immersive.prototype.wheel = function (e) {
    if (this.zoomed() || this.core.$items.length < 2) { return; }
    var d = e.deltaY || e.deltaX;
    if (!d) { return; }
    e.preventDefault();

    var now = new Date().getTime();
    if (now - this.wheelAt < CFG.wheelMs) { return; }   // one slide per gesture
    this.wheelAt = now;

    if (d > 0) { this.core.goToNextSlide(); } else { this.core.goToPrevSlide(); }
  };

  /* --- keyboard ---------------------------------------------------------- */

  Immersive.prototype.initKeys = function () {
    var self = this;

    // Bound on window, like lightGallery's own keyPress() -- but keyPress() runs
    // at build():215, after the module constructors at :207, so our handler is
    // registered first and runs first. That ordering is what lets the Esc branch
    // below pre-empt lightGallery's "Esc closes the gallery".
    $(window).on('keydown.imm', function (e) {
      if (e.altKey || e.ctrlKey || e.metaKey) { return; }

      // e.key for real keyboards of any layout, keyCode as the legacy fallback.
      var isF = e.key ? (e.key === 'f' || e.key === 'F') : (e.keyCode === 70);
      if (isF && !$(e.target).is('input, textarea, select')) {
        e.preventDefault();
        self.toggleFullscreen();
        return;
      }

      // Two-stage Esc: leave fullscreen first, keep the photo open; a second Esc
      // then closes the gallery through lightGallery's own handler. If the
      // browser consumed Esc for its own fullscreen exit we never see it here,
      // and the fullscreenchange handler does the same job.
      var isEsc = e.key ? (e.key === 'Escape' || e.key === 'Esc') : (e.keyCode === 27);
      if (!isEsc) { return; }

      if (fsNode()) {
        e.preventDefault();
        e.stopImmediatePropagation();
        fsExit();
        return;
      }

      // lightGallery's Esc branch (:949-953) closes the thumbnail panel first and
      // only closes the gallery on the next press. The strip auto-hides now, so
      // that first Esc would look like it did nothing at all. When the strip is
      // already out of sight, drop the class so the handler we run just ahead of
      // goes straight to closing the gallery.
      if (self.core.$outer.hasClass('lg-hide-items')) {
        self.core.$outer.removeClass('lg-thumb-open');
      }
    });
  };

  /* --- fullscreen -------------------------------------------------------- */

  Immersive.prototype.initFullscreen = function () {
    var self = this;

    // Glyphs \e20c / \e20d are already in lightgallery.css:599-604 and the lg
    // icon font ships in public/lightgallery/fonts -- nothing to add.
    // The button stays even where the API is missing (iPhone Safari before
    // iOS 17.4); it then drives the CSS-only maximise mode instead, which is
    // exactly the hook the shipped lg-fullscreen.js denies itself by returning
    // early on !fullscreenEnabled.
    this.$btn = $('<span class="lg-fullscreen lg-icon" role="button" tabindex="0"' +
                  ' title="Fullscreen" aria-label="Toggle fullscreen"></span>');
    this.core.$outer.find('.lg-toolbar').append(this.$btn);
    this.$btn.on('click.imm', function () { self.toggleFullscreen(); });

    // Read the real state instead of blind-toggling a class (the bug in
    // lg-fullscreen.js:73), so Esc, Android Back, F11 and system exits all
    // stay in sync.
    $(document).on('fullscreenchange.imm webkitfullscreenchange.imm ' +
                   'mozfullscreenchange.imm MSFullscreenChange.imm', function () {
      self.syncFullscreen();
      self.reset();                 // the frame just changed size
    });

    this.syncFullscreen();
  };

  Immersive.prototype.toggleFullscreen = function () {
    if (!fsRequest) {
      this.core.$outer.toggleClass('imm-maximise');
    } else if (fsNode()) {
      fsExit();
    } else {
      fsEnter();
    }
    this.syncFullscreen();
  };

  Immersive.prototype.syncFullscreen = function () {
    var $outer = this.core.$outer;
    $outer.toggleClass('lg-fullscreen-on',
                       !!fsNode() || $outer.hasClass('imm-maximise'));

    // Leaflet lays its tiles out for the old container size; nudge it once the
    // fullscreen transition has settled. Guarded so a thumbsup upgrade that
    // drops or renames lg-exif cannot throw here.
    var exif = this.core.modules && this.core.modules.exif;
    var map = exif && exif.map;
    if (map && map.invalidateSize) {
      setTimeout(function () { map.invalidateSize(); }, 300);
    }
  };

  /* --- teardown ---------------------------------------------------------- */

  Immersive.prototype.destroy = function () {
    var l = this.listeners;
    var i;

    // A tap up to CFG.tapMs before closing would otherwise fire toggleBars() on an
    // $outer that has already been removed; offTimer likewise must not outlive us.
    clearTimeout(this.tapTimer);
    clearTimeout(this.offTimer);
    // The capture flag is what must match on removal; the options object is not
    // required.
    for (i = 0; i < l.length; i++) {
      l[i][0].removeEventListener(l[i][1], l[i][2], true);
    }
    this.listeners = [];

    if (!this.core) { return; }

    fsExit();                       // never strand the album grid in fullscreen
    $(document).off('.imm');
    $(window).off('.imm');
    this.core.$el.off('.imm');
    if (this.$btn) { this.$btn.off('.imm'); }
    this.core.$outer.removeClass('imm-maximise imm-active lg-fullscreen-on');
    this.stole = false;             // the slides are about to be removed anyway
    this.reset();
  };

  $.fn.lightGallery.modules.immersive = Immersive;

}(window.jQuery, window, document));
