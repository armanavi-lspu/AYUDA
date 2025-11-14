// Assumes Leaflet, MarkerCluster, and Turf are loaded via template
(async function() {
  const mapElement = document.getElementById('admin-map');
  if (!mapElement) return;

  const map = L.map('admin-map').setView([11.0, 122.5], 10); // set to your province center

  // Basemap (OpenStreetMap)
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '© OpenStreetMap contributors'
  }).addTo(map);

  // Layers
  let barangayLayer = L.geoJSON(null, {
    style: styleBarangay,
    onEachFeature: onEachBarangay
  }).addTo(map);

  const markerCluster = L.markerClusterGroup();
  map.addLayer(markerCluster);

  // Load data
  async function loadData() {
    try {
      const [bResp, cResp] = await Promise.all([
        fetch('/maps/barangays.geojson'),
        fetch('/maps/cases.geojson')
      ]);
      const barangays = await bResp.json();
      const cases = await cResp.json();

      // Add barangays (choropleth by served_count)
      barangayLayer.clearLayers();
      barangayLayer.addData(barangays);
      map.fitBounds(barangayLayer.getBounds());

      // Add case markers
      markerCluster.clearLayers();
      if (cases && cases.features) {
        cases.features.forEach(f => {
          if (!f.geometry) return;
          const [lng, lat] = f.geometry.coordinates;
          const props = f.properties || {};
          const m = L.marker([lat, lng]);
          m.bindPopup(`<b>Case:</b> ${props.case_id || '—'}<br><b>Status:</b> ${props.status || '—'}`);
          markerCluster.addLayer(m);
        });
      }
    } catch (err) {
      console.error('Failed to load map data', err);
    }
  }

  function styleBarangay(feature) {
    const count = (feature && feature.properties && feature.properties.served_count) || 0;
    const fill = getColorByCount(count);
    return {
      color: '#333',
      weight: 1,
      fillColor: fill,
      fillOpacity: 0.6
    };
  }

  function getColorByCount(d) {
    return d > 100 ? '#08519c' :
           d > 50  ? '#3182bd' :
           d > 20  ? '#6baed6' :
           d > 5   ? '#bdd7e7' :
                    '#eff3ff';
  }

  function onEachBarangay(feature, layer) {
    const p = feature.properties || {};
    const html = `<b>${p.name || 'Barangay'}</b><br/>Served: ${p.served_count || 0}<br/>Last update: ${p.last_update || '—'}`;
    layer.bindPopup(html);
    layer.on('mouseover', function() { this.setStyle({ weight:2 }); });
    layer.on('mouseout', function() { barangayLayer.resetStyle(this); });
  }

  // Radius selection logic
  let radiusMode = false;
  let currentCircle = null;
  document.getElementById('set-radius-btn').addEventListener('click', () => {
    radiusMode = true;
    alert('Click on map to set center for radius selection.');
  });

  map.on('click', function(e) {
    if (!radiusMode) return;
    radiusMode = false;
    const meters = parseFloat(document.getElementById('radius-input').value) || 1000;
    if (currentCircle) { map.removeLayer(currentCircle); currentCircle = null; }
    currentCircle = L.circle(e.latlng, { radius: meters, color: '#ff7800', fillOpacity: 0.1 }).addTo(map);

    // Build turf buffer and find intersecting barangays
    const circleGeo = turf.circle([e.lng, e.lat], meters/1000, { steps: 64, units: 'kilometers' });
    const intersecting = [];
    barangayLayer.eachLayer(layer => {
      if (!layer.feature) return;
      const poly = layer.feature;
      if (turf.booleanIntersect(circleGeo, poly)) {
        layer.setStyle({ fillOpacity: 0.9, weight:2 });
        intersecting.push(layer.feature.properties);
      } else {
        barangayLayer.resetStyle(layer);
      }
    });

    // Show results in console or popup
    const n = intersecting.length;
    L.popup()
      .setLatLng(e.latlng)
      .setContent(`<b>${n}</b> barangay(s) intersect the selected radius.`)
      .openOn(map);

    // Optionally send intersecting barangay ids to server for further query
    console.log('Intersecting barangays', intersecting);
  });

  document.getElementById('refresh-btn').addEventListener('click', loadData);

  // initial load
  loadData();
})();