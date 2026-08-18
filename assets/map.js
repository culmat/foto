/*
  Map mode for the Cullmann Gallery -- map.html only.

  Reads the sidecars exif2geojson.py writes (geo/index.json, then one
  geo/<PageStem>.geojson per album) and plots every geotagged photo on
  OpenStreetMap. Nothing in media/ carries EXIF, so those sidecars are the only
  source of coordinates the published site has.

  With no query string it maps every album at once; with ?album=<PageStem> it
  maps one and offers a chronological track through it.

  Plain DOM and ES5-ish syntax to match assets/immersive.js and the vendored
  lightGallery plugins -- there is no build step in this repo. Deliberately does
  not load jQuery or lightGallery: lg-exif.min.js, which every album page pulls
  in, bundles its own Leaflet 1.1.1 onto window.L and would fight ours.
*/
(function () {
  'use strict';

  // Single-host form. The {s}.tile.openstreetmap.org subdomain pattern that
  // lg-exif still uses is deprecated.
  var TILE_URL = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
  var TILE_ATTRIB =
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
  var DARK_KEY = 'foto-map-dark';

  var map = null;
  var cluster = null;
  var track = null;

  // --- small helpers -----------------------------------------------------

  function esc(text) {
    return String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function param(name) {
    var found = new RegExp('[?&]' + name + '=([^&]*)').exec(window.location.search);
    return found ? decodeURIComponent(found[1].replace(/\+/g, ' ')) : null;
  }

  function stemOf(page) {
    return String(page).replace(/\.html$/, '');
  }

  function getJSON(url) {
    return fetch(url, { cache: 'no-cache' }).then(function (response) {
      if (!response.ok) {
        throw new Error(url + ': HTTP ' + response.status);
      }
      return response.json();
    });
  }

  function note(html) {
    var el = document.getElementById('map-note');
    el.innerHTML = html;
    el.hidden = false;
  }

  // --- rendering ---------------------------------------------------------

  function pinFor(properties) {
    return L.divIcon({
      className: 'photo-pin',
      html: '<img loading="lazy" alt="" src="' + esc(encodeURI(properties.thumb)) + '">',
      iconSize: [46, 46],
      iconAnchor: [23, 23],
      popupAnchor: [0, -25]
    });
  }

  function popupFor(properties) {
    // lg-hash (loaded on the album pages by patchHtml.py) reads this hash and
    // jumps straight to that slide. galleryId is lightGallery's default of 1.
    // &amp; because this is an HTML attribute; the browser hands lg-hash a
    // plain &.
    var href = encodeURI(properties.page);
    if (properties.slide != null) {
      href += '#lg=1&amp;slide=' + properties.slide;
    }
    var when = properties.date ? esc(properties.date.slice(0, 10)) : '';

    return '<div class="pop">' +
      '<a href="' + href + '">' +
        '<img alt="" src="' + esc(encodeURI(properties.small)) + '">' +
      '</a>' +
      '<div class="meta"><b>' + esc(properties.album) + '</b>' +
        (when ? '<span>' + when + '</span>' : '') +
      '</div>' +
      '<a class="open" href="' + href + '">Open in album &rarr;</a>' +
    '</div>';
  }

  function markerFor(feature) {
    var properties = feature.properties;
    var coords = feature.geometry.coordinates;   // RFC 7946: [lon, lat, alt]
    var marker = L.marker([coords[1], coords[0]], {
      icon: pinFor(properties),
      thumb: encodeURI(properties.thumb),        // read back by clusterIcon
      title: properties.album + ' - ' + properties.file
    });
    marker.bindPopup(popupFor(properties), { minWidth: 220, maxWidth: 300 });
    return marker;
  }

  function clusterIcon(group) {
    var children = group.getAllChildMarkers();
    return L.divIcon({
      className: 'photo-cluster',
      html: '<img loading="lazy" alt="" src="' + esc(children[0].options.thumb) + '">' +
            '<b>' + group.getChildCount() + '</b>',
      iconSize: [52, 52],
      iconAnchor: [26, 26]
    });
  }

  function fitTo(bounds) {
    if (!bounds.isValid()) {
      return;
    }
    if (bounds.getNorthEast().equals(bounds.getSouthWest())) {
      map.setView(bounds.getCenter(), 15);      // a lone photo has no extent
    } else {
      map.fitBounds(bounds, { padding: [40, 40], maxZoom: 16 });
    }
  }

  // --- controls ----------------------------------------------------------

  function control(position, build) {
    var Control = L.Control.extend({
      options: { position: position },
      onAdd: function () {
        var container = L.DomUtil.create('div', 'map-ctl leaflet-bar');
        build(container);
        L.DomEvent.disableClickPropagation(container);
        L.DomEvent.disableScrollPropagation(container);
        return container;
      }
    });
    map.addControl(new Control());
  }

  function toggleButton(container, label, title, pressed, onToggle) {
    var button = L.DomUtil.create('button', '', container);
    button.type = 'button';
    button.innerHTML = label;
    button.title = title;
    button.setAttribute('aria-pressed', pressed ? 'true' : 'false');
    L.DomEvent.on(button, 'click', function () {
      var next = button.getAttribute('aria-pressed') !== 'true';
      button.setAttribute('aria-pressed', next ? 'true' : 'false');
      onToggle(next);
    });
    return button;
  }

  function addDarkToggle(dark) {
    control('topright', function (container) {
      toggleButton(container, '&#9681;', 'Dark basemap', dark, function (on) {
        document.body.classList.toggle('map-dark', on);
        try {
          window.localStorage.setItem(DARK_KEY, on ? '1' : '0');
        } catch (err) {
          /* Safari private browsing throws on setItem; the toggle still works. */
        }
      });
    });
  }

  function addTrackToggle() {
    control('topright', function (container) {
      toggleButton(container, '&#8599;', 'Chronological track', true, function (on) {
        if (on) {
          track.addTo(map);
        } else {
          map.removeLayer(track);
        }
      });
    });
  }

  // Newest first; albums without any dated photo go last, ties alphabetical.
  function byDateDesc(a, b) {
    var sa = a.start || '';
    var sb = b.start || '';
    if (sa !== sb) {
      if (!sa) return 1;
      if (!sb) return -1;
      return sb < sa ? -1 : 1;
    }
    return String(a.album).localeCompare(String(b.album));
  }

  function addAlbumPicker(index, current) {
    control('topleft', function (container) {
      var select = L.DomUtil.create('select', '', container);
      var all = L.DomUtil.create('option', '', select);
      all.value = '';
      all.textContent = 'All albums (' + index.length + ')';

      index.slice().sort(byDateDesc).forEach(function (entry) {
        var option = L.DomUtil.create('option', '', select);
        option.value = stemOf(entry.page);
        option.textContent = entry.album + ' (' + entry.count + ')';
        if (option.value === current) {
          option.selected = true;
        }
      });

      L.DomEvent.on(select, 'change', function () {
        window.location.href = select.value
          ? 'map.html?album=' + encodeURIComponent(select.value)
          : 'map.html';
      });
    });
  }

  // --- page chrome -------------------------------------------------------

  function setCrumb(entry) {
    var crumb = document.getElementById('crumb');
    if (entry) {
      document.title = 'Cullmann Gallery - ' + entry.album + ' Map';
      crumb.innerHTML = '&nbsp;/&nbsp;<a class="breadcrumb-item" href="' +
        esc(encodeURI(entry.page)) + '">' + esc(entry.album) + '</a>&nbsp;/&nbsp;Map';
    } else {
      crumb.innerHTML = '&nbsp;/&nbsp;Map';
    }
  }

  // --- entry point -------------------------------------------------------

  function render(index, entries, collections, album) {
    var features = [];
    collections.forEach(function (collection) {
      features = features.concat(collection.features || []);
    });

    if (!features.length) {
      note('No photos with location data yet.');
      return;
    }

    var dark = true;
    try {
      dark = window.localStorage.getItem(DARK_KEY) !== '0';
    } catch (err) {
      /* localStorage unavailable; fall back to the dark default. */
    }
    document.body.classList.toggle('map-dark', dark);

    // No attribution control: the overlay bar was unreadable over the tiles and
    // ate a strip of the map. The OpenStreetMap credit it would have shown is
    // required -- it is the condition under which their tiles may be used -- so
    // it lives in the page chrome instead, as #map-credit in map.html. That is
    // static markup, so the credit survives even if this script never runs.
    // TILE_ATTRIB is kept on the layer as the canonical string; nothing renders
    // it while attributionControl is off.
    map = L.map('photomap', { worldCopyJump: true, attributionControl: false });
    L.tileLayer(TILE_URL, { attribution: TILE_ATTRIB, maxZoom: 19 }).addTo(map);

    cluster = L.markerClusterGroup({
      iconCreateFunction: clusterIcon,
      showCoverageOnHover: false,
      maxClusterRadius: 60,
      chunkedLoading: true
    });
    features.forEach(function (feature) {
      cluster.addLayer(markerFor(feature));
    });
    map.addLayer(cluster);

    // One album: join its photos in the order they were taken. exif2geojson.py
    // already sorts features chronologically.
    if (album && entries.length === 1) {
      track = L.polyline(features.map(function (feature) {
        var coords = feature.geometry.coordinates;
        return [coords[1], coords[0]];
      }), { color: '#e8543f', weight: 2, opacity: 0.75, dashArray: '5 5' });
      track.addTo(map);
      addTrackToggle();
    }

    addDarkToggle(dark);
    addAlbumPicker(index, album || '');
    fitTo(cluster.getBounds());
    setCrumb(entries.length === 1 && album ? entries[0] : null);
  }

  function start() {
    var album = param('album');

    getJSON('geo/index.json').then(function (index) {
      if (!index.length) {
        setCrumb(null);
        note('No photos with location data yet. Run <code>exif2geojson.py</code> ' +
             'against the originals to generate the map data.');
        return;
      }

      var entries = album
        ? index.filter(function (entry) {
            return stemOf(entry.page) === album || entry.album === album;
          })
        : index;

      if (!entries.length) {
        setCrumb(null);
        note('No location data for &ldquo;' + esc(album) + '&rdquo;. ' +
             '<a href="map.html">Show all albums</a>.');
        return;
      }

      return Promise.all(entries.map(function (entry) {
        return getJSON(entry.file);
      })).then(function (collections) {
        render(index, entries, collections, album);
      });
    }).catch(function (err) {
      setCrumb(null);
      note('Could not load the map data (' + esc(err.message) + ').');
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
}());
