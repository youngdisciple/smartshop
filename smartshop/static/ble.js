'use strict';
const blePage = document.querySelector('.ble-page');
if (blePage) {
  const french = document.documentElement.lang === 'fr';
  const relativeTime = new Intl.RelativeTimeFormat(french ? 'fr' : 'en', {numeric: 'always'});
  const absoluteTime = new Intl.DateTimeFormat(french ? 'fr-CA' : 'en-CA', {dateStyle: 'medium', timeStyle: 'medium'});
  const secondsSince = value => Math.max(0, (Date.now() - Date.parse(value)) / 1000);
  function drawLight(metric, reading) {
    const visual = metric.querySelector('.ble-light-visual');
    if (!visual) return;
    const meter = reading.light_meter;
    visual.dataset.lightState = meter.state;
    visual.setAttribute('aria-label', reading.label + ': ' + meter.label);
    visual.setAttribute('role', reading.value === null ? 'img' : 'meter');
    for (const [attribute, value] of [['aria-valuemin', 0], ['aria-valuemax', meter.maximum],
      ['aria-valuenow', meter.bounded_value], ['aria-valuetext', reading.display + ' ' + reading.unit + ' · ' + meter.label]]) {
      if (reading.value === null) visual.removeAttribute(attribute);
      else visual.setAttribute(attribute, value);
    }
    visual.querySelector('.ble-light-fill').style.height = meter.percent + '%';
    visual.querySelector('[data-light-maximum]').textContent = meter.maximum_label;
    metric.querySelector('.ble-light-caption').textContent = meter.label;
    metric.querySelector('.ble-light-cutoff').textContent = meter.threshold_label;
  }
  function updateTimes() {
    for (const node of blePage.querySelectorAll('time[data-received-at]')) {
      const date = new Date(node.dataset.receivedAt);
      const seconds = secondsSince(node.dataset.receivedAt);
      if (!Number.isFinite(seconds)) continue;
      const [unit, divisor] = seconds < 60 ? ['second', 1] : seconds < 3600 ? ['minute', 60] : seconds < 86400 ? ['hour', 3600] : ['day', 86400];
      node.textContent = seconds < 10 ? (french ? 'À l’instant' : 'Just now') : relativeTime.format(-Math.floor(seconds / divisor), unit);
      node.title = absoluteTime.format(date);
    }
    for (const node of blePage.querySelectorAll('[data-freshness-at], [data-reading-at]')) {
      const timestamp = node.dataset.freshnessAt || node.dataset.readingAt;
      const seconds = secondsSince(timestamp);
      const state = !timestamp || !Number.isFinite(seconds) ? 'missing' : seconds <= 120 ? 'recent' : 'older';
      node.dataset.freshness = state;
      if (node.hasAttribute('data-freshness-at')) {
        node.textContent = french ? ({recent: 'Reçu récemment', older: 'Anciennes mesures', missing: 'En attente de données'})[state] : ({recent: 'Recently received', older: 'Older readings', missing: 'Waiting for data'})[state];
      }
      const old = node.querySelector('.ble-old-reading');
      if (old) old.hidden = state !== 'older';
    }
  }
  const liveStatus = document.querySelector('#ble-live-status');
  const liveToggle = document.querySelector('#ble-live-toggle');
  const manualRefresh = blePage.querySelector('.ble-manual-refresh');
  const canStream = Boolean(blePage.dataset.liveUrl && 'EventSource' in window);
  let stream = null;
  let userPaused = false;
  let leaving = false;
  const words = french ? {
    live: 'Mises à jour en direct', starting: 'Démarrage du récepteur…',
    reconnecting: 'Reconnexion…', error: 'Récepteur indisponible · nouvelle tentative…',
    paused: 'Mises à jour en pause', hidden: 'En pause pendant que cet onglet est masqué',
    pause: 'Mettre en pause', resume: 'Reprendre les mises à jour',
    received: 'Reçu ', lastReceived: 'Dernière réception · ', missing: 'Aucune mesure reçue',
    ps: 'Niveau de lumière · échelle PS', motion: 'Lors de la dernière mesure reçue',
    empty: 'Aucun capteur connecté', manual: 'Actualisation manuelle'
  } : {
    live: 'Live updates', starting: 'Starting receiver…', reconnecting: 'Reconnecting…',
    error: 'Receiver unavailable · retrying…', paused: 'Updates paused',
    hidden: 'Paused while this tab is hidden', pause: 'Pause updates', resume: 'Resume updates',
    received: 'Received ', lastReceived: 'Last received · ', missing: 'No reading yet',
    ps: 'Sensor light level · PS scale', motion: 'At the last received reading',
    empty: 'No sensors connected', manual: 'Manual refresh'
  };
  const receiverError = document.createElement('p');
  receiverError.className = 'notice ble-live-error'; receiverError.hidden = true;
  receiverError.setAttribute('role', 'alert');
  document.querySelector('#ble-progress').after(receiverError);
  function setLiveState(state, message = '') {
    blePage.dataset.liveState = state;
    if (liveStatus) {
      const text = words[state] || words.starting;
      if (liveStatus.textContent !== text) liveStatus.textContent = text;
      liveStatus.dataset.state = state;
      liveStatus.title = message;
    }
    receiverError.hidden = !message;
    if (receiverError.textContent !== message) receiverError.textContent = message;
  }
  function setTime(parent, info, prefix = '') {
    parent.textContent = prefix;
    if (info.iso) {
      const time = document.createElement('time');
      time.dateTime = info.iso; time.dataset.receivedAt = info.iso;
      time.title = info.absolute; time.textContent = info.relative; parent.append(time);
    } else parent.append(document.createTextNode(words.missing));
  }
  function renderSensors(sensors) {
    const addresses = new Set(sensors.map(sensor => sensor.anchor));
    for (const card of blePage.querySelectorAll('.ble-sensor')) {
      if (!addresses.has(card.id)) card.remove();
    }
    for (const sensor of sensors) {
      const card = document.getElementById(sensor.anchor);
      if (!card) continue;
      setTime(card.querySelector('.ble-last-seen'), sensor.receipt, words.lastReceived);
      card.querySelector('.ble-freshness').dataset.freshnessAt = sensor.receipt.iso;
      const battery = card.querySelector('.ble-battery');
      battery.title = sensor.battery.receipt.absolute;
      battery.querySelector('strong').textContent = sensor.battery.display + (sensor.battery.value === null ? '' : '%');
      const metrics = card.querySelectorAll('.ble-metric');
      sensor.readings.forEach((reading, index) => {
        const metric = metrics[index];
        metric.dataset.readingAt = reading.receipt.iso;
        metric.querySelector('h3').textContent = reading.label;
        const sensorGauge = metric.querySelector('.ble-sensor-gauge');
        if (sensorGauge) {
          const gauge = reading.gauge;
          sensorGauge.classList.toggle('gauge-error', gauge.error);
          sensorGauge.setAttribute('aria-label', reading.label + ': ' + gauge.label);
          sensorGauge.querySelector('.gauge-fill').style.strokeDasharray = gauge.dash + ' 283';
          sensorGauge.querySelector('.gauge-needle').style.transform = 'rotate(' + gauge.angle + 'deg)';
          sensorGauge.querySelector('.gauge-value').textContent = gauge.label;
        } else {
          const value = metric.querySelector('.ble-metric-value');
          value.textContent = reading.display;
          if (reading.value !== null && reading.unit) {
            const unit = document.createElement('span'); unit.textContent = reading.unit; value.append(unit);
          }
        }
        if (reading.key === 'light' || reading.key === 'illuminance') drawLight(metric, reading);
        if (reading.key === 'motion') {
          const visual = metric.querySelector('.ble-motion-visual');
          visual.dataset.motion = reading.value === null ? 'unknown' : reading.value ? 'detected' : 'clear';
          visual.setAttribute('aria-label', reading.label + ': ' + reading.display);
        }
        setTime(metric.querySelector('.ble-metric-time'), reading.receipt, reading.value === null ? '' : words.received);
        const help = metric.querySelector('.ble-metric-help');
        help.textContent = reading.key === 'light' ? words.ps : reading.key === 'motion' ? words.motion : '';
        help.hidden = !help.textContent;
      });
      card.querySelector('.ble-missing-note').hidden = !sensor.missing;
      card.querySelector('[data-ble-signal]').textContent = sensor.rssi === null ? '—' : sensor.rssi + ' dBm';
      setTime(card.querySelector('[data-ble-battery-time]'), sensor.battery.receipt);
      card.querySelector('[data-ble-absolute]').textContent = sensor.receipt.absolute || words.missing;
      const ps = card.querySelector('[data-ble-ps]');
      ps.hidden = !sensor.secondary_light;
      if (sensor.secondary_light) setTime(ps.querySelector('dd'), sensor.secondary_light.receipt, sensor.secondary_light.display + ' · ');
    }
    const count = blePage.querySelector('.ble-count');
    if (count) count.textContent = String(sensors.length);
    updateTimes();
  }
  function closeStream() {
    if (stream) { stream.close(); stream = null; }
  }
  function startStream() {
    if (!canStream || stream || userPaused || leaving || document.hidden) return;
    setLiveState('starting');
    const source = new EventSource(blePage.dataset.liveUrl);
    stream = source;
    source.addEventListener('renew', () => {
      if (stream !== source) return;
      closeStream();
      startStream();
    });
    source.onmessage = event => {
      if (stream !== source) return;
      try {
        const data = JSON.parse(event.data);
        if (Array.isArray(data.sensors)) renderSensors(data.sensors);
        setLiveState(data.state === 'receiving' ? 'live' : data.state === 'error' ? 'error' : 'starting', data.message || '');
        if (Array.isArray(data.sensors) && data.sensors.length === 0) {
          closeStream(); setLiveState('empty');
          if (liveToggle) liveToggle.hidden = true;
        }
      } catch (error) { setLiveState('reconnecting'); }
    };
    source.onerror = () => {
      if (stream === source && !userPaused && !leaving && !document.hidden) {
        if (!receiverError.hidden) return;
        setLiveState('reconnecting');
      }
    };
  }
  updateTimes();
  // This timer only ages timestamps. Readings arrive over one persistent stream.
  window.setInterval(updateTimes, 30000);
  if (canStream) {
    liveToggle.hidden = false;
    if (manualRefresh) manualRefresh.hidden = true;
    liveToggle.addEventListener('click', () => {
      userPaused = !userPaused;
      liveToggle.textContent = userPaused ? words.resume : words.pause;
      if (userPaused) { closeStream(); setLiveState('paused'); } else startStream();
    });
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) { closeStream(); setLiveState(userPaused ? 'paused' : 'hidden'); }
      else if (!userPaused) startStream();
    });
    startStream();
  } else if (liveStatus) setLiveState('manual');
  for (const form of blePage.querySelectorAll('form[data-ble-scan]')) {
    form.addEventListener('submit', event => {
      if (blePage.getAttribute('aria-busy') === 'true') {
        event.preventDefault();
        return;
      }
      // Disabled submit buttons are omitted from form data. Preserve the action.
      const action = document.createElement('input');
      action.type = 'hidden'; action.name = 'action';
      action.value = event.submitter ? event.submitter.value : form.querySelector('[name="action"]').value;
      form.append(action);
      blePage.setAttribute('aria-busy', 'true');
      document.querySelector('#ble-progress').hidden = false;
      for (const button of blePage.querySelectorAll('button')) button.disabled = true;
    });
  }
  for (const form of blePage.querySelectorAll('form')) {
    form.addEventListener('submit', () => { leaving = true; closeStream(); });
  }
  window.addEventListener('pagehide', () => { leaving = true; closeStream(); });
  window.addEventListener('pageshow', () => {
    leaving = false;
    blePage.removeAttribute('aria-busy');
    document.querySelector('#ble-progress').hidden = true;
    for (const button of blePage.querySelectorAll('button')) button.disabled = false;
    for (const input of blePage.querySelectorAll('form[data-ble-scan] input[name="action"]')) input.remove();
    updateTimes();
    startStream();
  });
}
