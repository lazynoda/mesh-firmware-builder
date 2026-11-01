// Families whose boards can have WiFi. rp2040 is mixed (the Pico W has it, the
// plain Pico does not), so it stays in: showing an inert field beats hiding a
// real one, and nrf52840 genuinely has no WiFi radio at all.
const WIFI_FAMILIES = new Set(["esp32", "esp32-s3", "esp32-c3", "esp32-c6", "rp2040"]);

// Keys the dedicated controls own. Everything else in the selected tag's template
// is offered in the free-form section, so the two sets must never overlap.
const FORM_MANAGED_KEYS = new Set([
  "USERPREFS_CHANNELS_TO_WRITE",
  "USERPREFS_CONFIG_DEVICE_NODE_INFO_BROADCAST_SECS",
  "USERPREFS_CONFIG_DEVICE_REBROADCAST_MODE",
  "USERPREFS_CONFIG_DEVICE_ROLE",
  "USERPREFS_BLOCK_POSITION_ON_EVENT_CHANNEL",
  "USERPREFS_CONFIG_DEVICE_TELEM_UPDATE_INTERVAL",
  "USERPREFS_CONFIG_GPS_MODE",
  "USERPREFS_CONFIG_GPS_UPDATE_INTERVAL",
  "USERPREFS_CONFIG_POSITION_BROADCAST_INTERVAL",
  "USERPREFS_CONFIG_SMART_POSITION_ENABLED",
  "USERPREFS_FIXED_GPS",
  "USERPREFS_FIXED_GPS_ALT",
  "USERPREFS_FIXED_GPS_LAT",
  "USERPREFS_FIXED_GPS_LON",
  "USERPREFS_CONFIG_LORA_IGNORE_MQTT",
  "USERPREFS_CONFIG_LORA_REGION",
  "USERPREFS_CONFIG_OWNER_LONG_NAME",
  "USERPREFS_CONFIG_OWNER_SHORT_NAME",
  "USERPREFS_CONFIG_SECURITY_IS_MANAGED",
  "USERPREFS_CONFIG_SECURITY_PACKET_SIGNATURE_POLICY",
  "USERPREFS_FIXED_BLUETOOTH",
  "USERPREFS_LORACONFIG_MODEM_PRESET",
  "USERPREFS_LORACONFIG_TX_POWER",
  "USERPREFS_MQTT_ADDRESS",
  "USERPREFS_MQTT_ENABLED",
  "USERPREFS_MQTT_ENCRYPTION_ENABLED",
  "USERPREFS_MQTT_PASSWORD",
  "USERPREFS_MQTT_ROOT_TOPIC",
  "USERPREFS_MQTT_TLS_ENABLED",
  "USERPREFS_MQTT_USERNAME",
  "USERPREFS_NETWORK_WIFI_ENABLED",
  "USERPREFS_NETWORK_WIFI_PSK",
  "USERPREFS_NETWORK_WIFI_SSID",
  "USERPREFS_TZ_STRING",
  "USERPREFS_USE_ADMIN_KEY_0",
  "USERPREFS_USE_ADMIN_KEY_1",
  "USERPREFS_USE_ADMIN_KEY_2",
]);

// The form opens on the custom LoRa profile most users build, so the primary
// channel is named for it instead of for a modem preset that is switched off.
// Picking a preset still renames it, via syncPresetChannelName().
const DEFAULT_CHANNEL_NAME = "SFNarrow";

const state = {
  deviceFamilies: {},
  deviceLabels: {},
  // Boards the selected firmware lists but cannot build yet: id -> {reason, issue}.
  unavailableDevices: {},
  // Boards with a Meshtastic UI build in the selected firmware version.
  muiDevices: new Set(),
  // The board the Meshtastic UI checkbox was last defaulted for.
  muiDefaultFor: null,
  firmwares: [],
  firmwareNames: {},
  versions: [],
  extraPrefs: [],
  presetChannelName: DEFAULT_CHANNEL_NAME,
  templateExamples: {},
  templateDefaults: {},
  currentBuildToken: null,
  buildViewOnly: false,
  pollTimer: null,
  templateKeys: new Set(),
  channels: [],
  statusIsError: false,
  statusKey: null,
  buildOptions: null,
  codeOptionsAvailable: false,
  codeOptionsNative: false,
  maxChannels: 3,
  lastBuild: null,
  // Queue position and time estimate from the server, refreshed with every poll.
  lastQueue: null,
  lastDownloadUrl: null,
  lastBuildUrl: null,
};

const $ = (id) => document.getElementById(id);
const encoder = new TextEncoder();

// Third element is the firmware version that introduced the enum value.
const REGION_OPTIONS = [
  ["EU_868", "EU 868 MHz"],
  ["EU_433", "EU 433 MHz"],
  ["EU_866", "EU 866 MHz", "2.7.23"],
  ["EU_874", "EU 874 MHz", "2.7.23"],
  ["EU_917", "EU 917 MHz", "2.7.23"],
  ["EU_N_868", "EU narrow 868 MHz", "2.7.23"],
  ["US", "US 915 MHz"],
  ["ANZ", "Australia / New Zealand 915 MHz"],
  ["ANZ_433", "Australia / New Zealand 433 MHz"],
  ["BR_902", "Brazil 902 MHz"],
  ["CN", "China"],
  ["IN", "India"],
  ["JP", "Japan"],
  ["KR", "Korea"],
  ["KZ_433", "Kazakhstan 433 MHz"],
  ["KZ_863", "Kazakhstan 863 MHz"],
  ["MY_433", "Malaysia 433 MHz"],
  ["MY_919", "Malaysia 919 MHz"],
  ["NP_865", "Nepal 865 MHz"],
  ["NZ_865", "New Zealand 865 MHz"],
  ["PH_433", "Philippines 433 MHz"],
  ["PH_868", "Philippines 868 MHz"],
  ["PH_915", "Philippines 915 MHz"],
  ["RU", "Russia"],
  ["SG_923", "Singapore 923 MHz"],
  ["TH", "Thailand"],
  ["TW", "Taiwan"],
  ["UA_433", "Ukraine 433 MHz"],
  ["UA_868", "Ukraine 868 MHz"],
  ["LORA_24", "2.4 GHz"],
  ["ITU1_2M", "ITU region 1, 2 m", "2.7.23"],
  ["ITU2_2M", "ITU region 2, 2 m", "2.7.25"],
  ["ITU3_2M", "ITU region 3, 2 m", "2.7.25"],
  ["ITU1_70CM", "ITU region 1, 70 cm", "2.8.0"],
  ["ITU2_70CM", "ITU region 2, 70 cm", "2.8.0"],
  ["ITU3_70CM", "ITU region 3, 70 cm", "2.8.0"],
  ["ITU2_125CM", "ITU region 2, 1.25 m", "2.8.0"],
];

const ROLE_OPTIONS = [
  ["CLIENT", "Client"],
  ["CLIENT_MUTE", "Client mute"],
  ["CLIENT_HIDDEN", "Client hidden"],
  ["TRACKER", "Tracker"],
  ["SENSOR", "Sensor"],
  ["TAK", "TAK"],
  ["TAK_TRACKER", "TAK tracker"],
];

const PRESET_OPTIONS = [
  ["LONG_FAST", "Long fast"],
  ["LONG_MODERATE", "Long moderate"],
  ["MEDIUM_FAST", "Medium fast"],
  ["MEDIUM_SLOW", "Medium slow"],
  ["MEDIUM_TURBO", "Medium turbo", "2.8.0"],
  ["SHORT_FAST", "Short fast"],
  ["SHORT_SLOW", "Short slow"],
  ["SHORT_TURBO", "Short turbo"],
  ["LONG_TURBO", "Long turbo"],
  ["LITE_FAST", "Lite fast", "2.7.23"],
  ["LITE_SLOW", "Lite slow", "2.7.23"],
  ["NARROW_FAST", "Narrow fast", "2.7.23"],
  ["NARROW_SLOW", "Narrow slow", "2.7.23"],
  ["TINY_FAST", "Tiny fast", "2.8.0"],
  ["TINY_SLOW", "Tiny slow", "2.8.0"],
];

const GPS_MODE_OPTIONS = [
  ["ENABLED", "Enabled"],
  ["DISABLED", "Disabled"],
  ["NOT_PRESENT", "Not present"],
];

const REBROADCAST_OPTIONS = [
  ["ALL", "All"],
  ["ALL_SKIP_DECODING", "All, skip decoding"],
  ["LOCAL_ONLY", "Local only"],
  ["KNOWN_ONLY", "Known only"],
  ["CORE_PORTNUMS_ONLY", "Core portnums only"],
  ["NONE", "None"],
];

const SIGNATURE_POLICY_OPTIONS = [
  ["PACKET_SIGNATURE_POLICY_COMPATIBLE", "Compatible"],
  ["PACKET_SIGNATURE_POLICY_BALANCED", "Balanced"],
  ["PACKET_SIGNATURE_POLICY_STRICT", "Strict"],
];

// Firmware bandwidth codes are not all the real value in kHz.
const BANDWIDTH_LABELS = { 31: "31.25", 62: "62.5" };

// Position precision values the Meshtastic clients expose: 0 hides the position,
// 32 sends it exact, 10..19 truncate the coordinates to that many bits.
const PRECISION_STEPS = [0, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 32];
const DEFAULT_PRECISION_INDEX = PRECISION_STEPS.indexOf(14);

// 23.3 km at 10 bits, halved per extra bit: same table the Meshtastic docs publish.
function precisionLabel(precision) {
  const bits = Number(precision);
  if (bits === 0) return t("channel.precisionOff");
  if (bits >= 32) return t("channel.precisionExact");
  const metres = 23300 / 2 ** (bits - 10);
  return metres >= 1000 ? `~${(metres / 1000).toFixed(1)} km` : `~${Math.round(metres)} m`;
}

// Minimal combobox: a text box that filters its list by substring. <datalist> would
// be less code, but iOS Safari barely supports it and this page is used on phones.
// The visible input is only for searching; the hidden .combo-value holds the value
// and fires `change`, so the rest of the form reads it like any other field.
function comboHtml(items, selectedValue, { valueAttrs = "", placeholder = "" } = {}) {
  const selected = items.find((item) => item.value === selectedValue);
  return `
    <div class="combo">
      <input class="combo-input" type="text" autocomplete="off" role="combobox" aria-expanded="false"
        aria-autocomplete="list" placeholder="${escapeHtml(placeholder)}"
        value="${escapeHtml(selected ? selected.label : "")}">
      <input class="combo-value" type="hidden" ${valueAttrs} value="${escapeHtml(selected ? selected.value : "")}">
      <ul class="combo-list" role="listbox" hidden>
        ${items
          .map(
            (item) =>
              `<li role="option" data-value="${escapeHtml(item.value)}"${item.className ? ` class="${escapeHtml(item.className)}"` : ""}${item.value === selectedValue ? ' aria-selected="true"' : ""}>${escapeHtml(item.label)}</li>`,
          )
          .join("")}
      </ul>
    </div>`;
}

function closeCombos(except = null) {
  for (const root of document.querySelectorAll(".combo")) {
    if (root === except) continue;
    setComboOpen(root, false);
  }
}

// Punctuation is dropped from both sides so "promicro" finds "Pro-micro" and
// "gpsmode" finds "CONFIG_GPS_MODE".
function comboNormalize(text) {
  return text.toLowerCase().replace(/[^a-z0-9]/g, "");
}

function setComboOpen(root, open) {
  root.querySelector(".combo-list").hidden = !open;
  root.querySelector(".combo-input").setAttribute("aria-expanded", String(open));
}

// Opening shows everything: the box holds the current label, which would otherwise
// filter the list down to the one option already chosen.
function openCombo(root) {
  for (const item of root.querySelectorAll(".combo-list li")) item.hidden = false;
  setComboOpen(root, true);
  const input = root.querySelector(".combo-input");
  if (!input.readOnly) input.select();
}

function filterCombo(root) {
  const query = comboNormalize(root.querySelector(".combo-input").value);
  let visible = 0;
  for (const item of root.querySelectorAll(".combo-list li")) {
    item.hidden = query !== "" && !comboNormalize(item.textContent).includes(query);
    if (!item.hidden) visible += 1;
  }
  setComboOpen(root, visible > 0);
}

// Typing without picking must not leave a label that contradicts the stored value.
function restoreComboLabel(root) {
  const current = root.querySelector(".combo-value").value;
  const item = Array.from(root.querySelectorAll(".combo-list li")).find((li) => li.dataset.value === current);
  root.querySelector(".combo-input").value = item ? item.textContent.trim() : "";
}

function chooseComboItem(root, item) {
  const value = root.querySelector(".combo-value");
  value.value = item.dataset.value;
  root.querySelector(".combo-input").value = item.textContent.trim();
  for (const other of root.querySelectorAll(".combo-list li")) other.removeAttribute("aria-selected");
  item.setAttribute("aria-selected", "true");
  closeCombos();
  // Focus stays on the box (see the mousedown handler); a later click on it
  // must reopen the list, which focusin alone would not do.
  root.querySelector(".combo-input").blur();
  value.dispatchEvent(new Event("change", { bubbles: true }));
}

// Every <select> on the page gets the device picker's look. The native select
// stays in the DOM, hidden, as the .combo-value: code keeps reading .value,
// replacing its options and toggling .disabled, and the skin follows along.
// Short lists open as a plain menu; long ones can be filtered by typing.
const COMBO_FILTER_MIN_OPTIONS = 9;

function skinSelect(select) {
  if (select.dataset.skinned) return;
  select.dataset.skinned = "1";
  const root = document.createElement("div");
  root.className = "combo";
  const input = document.createElement("input");
  input.className = "combo-input";
  input.type = "text";
  input.autocomplete = "off";
  input.setAttribute("role", "combobox");
  input.setAttribute("aria-expanded", "false");
  input.setAttribute("aria-autocomplete", "list");
  const list = document.createElement("ul");
  list.className = "combo-list";
  list.setAttribute("role", "listbox");
  list.hidden = true;
  select.replaceWith(root);
  root.append(input, select, list);
  select.classList.add("combo-value");
  select.hidden = true;

  const syncLabel = () => {
    const option = select.selectedOptions[0];
    input.value = option ? option.textContent.trim() : "";
    for (const item of list.children) {
      if (item.dataset.value === select.value) item.setAttribute("aria-selected", "true");
      else item.removeAttribute("aria-selected");
    }
  };
  const syncOptions = () => {
    list.innerHTML = Array.from(select.options)
      .map(
        (option) =>
          `<li role="option" data-value="${escapeHtml(option.value)}">${escapeHtml(option.textContent.trim())}</li>`,
      )
      .join("");
    input.readOnly = select.options.length < COMBO_FILTER_MIN_OPTIONS;
    syncLabel();
  };
  const syncDisabled = () => {
    input.disabled = select.disabled;
  };

  // Assigning .value fires no event, so wrap the setter for this element.
  const proto = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value");
  Object.defineProperty(select, "value", {
    configurable: true,
    get: () => proto.get.call(select),
    set: (value) => {
      proto.set.call(select, value);
      syncLabel();
    },
  });
  select.addEventListener("change", syncLabel);
  new MutationObserver(() => {
    syncOptions();
    syncDisabled();
  }).observe(select, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ["disabled"] });
  syncOptions();
  syncDisabled();
}

function skinSelects() {
  document.querySelectorAll("select").forEach(skinSelect);
}

function bindCombos() {
  document.addEventListener("focusin", (event) => {
    const input = event.target.closest?.(".combo-input");
    if (!input) return closeCombos();
    const root = input.closest(".combo");
    closeCombos(root);
    openCombo(root);
  });
  document.addEventListener("input", (event) => {
    if (!event.target.matches?.(".combo-input")) return;
    filterCombo(event.target.closest(".combo"));
  });
  // Keep focus in the text box while an option is pressed, so the box never
  // blurs and refocuses mid-click.
  document.addEventListener("mousedown", (event) => {
    if (event.target.closest?.(".combo-list li")) event.preventDefault();
  });
  document.addEventListener("click", (event) => {
    const item = event.target.closest?.(".combo-list li");
    if (item) {
      // Every combo sits inside a <label>. Without this the click also
      // activates the label, which focuses the text box and reopens the list.
      event.preventDefault();
      return chooseComboItem(item.closest(".combo"), item);
    }
    if (!event.target.closest?.(".combo")) closeCombos();
  });
  document.addEventListener("keydown", (event) => {
    if (!event.target.matches?.(".combo-input")) return;
    const root = event.target.closest(".combo");
    if (event.key === "Escape") {
      restoreComboLabel(root);
      closeCombos();
    } else if (event.key === "Enter") {
      event.preventDefault();
      // A read-only menu shows every option, so Enter keeps the current one.
      const first = event.target.readOnly
        ? root.querySelector('.combo-list li[aria-selected="true"]')
        : root.querySelector(".combo-list li:not([hidden])");
      if (first) chooseComboItem(root, first);
    }
  });
  document.addEventListener("focusout", (event) => {
    if (!event.target.matches?.(".combo-input")) return;
    const root = event.target.closest(".combo");
    // Give a click on an option time to land before tidying up.
    setTimeout(() => {
      if (root.isConnected && !root.contains(document.activeElement)) {
        restoreComboLabel(root);
        setComboOpen(root, false);
      }
    }, 150);
  });
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || `HTTP ${response.status}`);
  }
  return payload;
}

function setStatus(message, isError = false, key = null) {
  const el = $("statusText");
  el.textContent = message;
  el.classList.toggle("status-error", isError);
  // On the permalink the panel already reports the build, so "Ready." is just
  // noise next to it. Keep the line for errors, and while the panel has nothing
  // in it yet.
  el.hidden = state.buildViewOnly && !isError && !$("result").hidden;
  state.statusIsError = isError;
  state.statusKey = key;
}

function setStatusKey(key) {
  setStatus(t(key), false, key);
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[char]);
}

function parseVersion(tag) {
  const match = /^v?(\d+)\.(\d+)\.(\d+)/.exec(String(tag).trim());
  return match ? [Number(match[1]), Number(match[2]), Number(match[3])] : null;
}

function versionAtLeast(tag, minimum) {
  const current = parseVersion(tag);
  const floor = parseVersion(minimum);
  if (!current || !floor) return false;
  for (let i = 0; i < 3; i += 1) {
    if (current[i] !== floor[i]) return current[i] > floor[i];
  }
  return true;
}

function optionHtml(options, selectedId, valuePrefix, tag = null) {
  return options
    .filter(([, , minVersion]) => !minVersion || !tag || versionAtLeast(tag, minVersion))
    .map(([id, label]) => {
      const value = `${valuePrefix}${id}`;
      return `<option value="${value}" ${id === selectedId ? "selected" : ""}>${escapeHtml(label)}</option>`;
    })
    .join("");
}

function fillSelect(el, options, prefix, fallbackId, tag) {
  const previous = el.value;
  el.innerHTML = optionHtml(options, fallbackId, prefix, tag);
  if (previous && Array.from(el.options).some((option) => option.value === previous)) {
    el.value = previous;
  }
}

function populateStaticSelects(tag = null) {
  fillSelect($("loraRegion"), REGION_OPTIONS, "meshtastic_Config_LoRaConfig_RegionCode_", "EU_868", tag);
  fillSelect($("deviceRole"), ROLE_OPTIONS, "meshtastic_Config_DeviceConfig_Role_", "CLIENT", tag);
  fillSelect($("modemPreset"), PRESET_OPTIONS, "meshtastic_Config_LoRaConfig_ModemPreset_", "LONG_FAST", tag);
  fillSelect(
    $("rebroadcastMode"),
    REBROADCAST_OPTIONS,
    "meshtastic_Config_DeviceConfig_RebroadcastMode_",
    "CORE_PORTNUMS_ONLY",
    tag,
  );
  fillSelect($("gpsMode"), GPS_MODE_OPTIONS, "meshtastic_Config_PositionConfig_GpsMode_", "ENABLED", tag);
  fillSelect(
    $("signaturePolicy"),
    SIGNATURE_POLICY_OPTIONS,
    "meshtastic_Config_SecurityConfig_PacketSignaturePolicy_",
    "PACKET_SIGNATURE_POLICY_BALANCED",
    tag,
  );
}

function numericOptionHtml(values, selected, labeller = String) {
  return values
    .map(
      (value) =>
        `<option value="${value}" ${value === selected ? "selected" : ""}>${escapeHtml(labeller(value))}</option>`,
    )
    .join("");
}

function range(min, max) {
  return Array.from({ length: max - min + 1 }, (_, index) => min + index);
}

async function loadBuildOptions() {
  state.buildOptions = await fetchJson("/api/build-options");
  const fields = state.buildOptions.customLora.fields;
  $("loraBandwidth").innerHTML = numericOptionHtml(
    fields.bandwidthKhz.choices,
    fields.bandwidthKhz.default,
    (value) => BANDWIDTH_LABELS[value] || String(value),
  );
  $("loraSpreadFactor").innerHTML = numericOptionHtml(
    range(fields.spreadFactor.min, fields.spreadFactor.max),
    fields.spreadFactor.default,
  );
  $("loraCodingRate").innerHTML = numericOptionHtml(
    range(fields.codingRate.min, fields.codingRate.max),
    fields.codingRate.default,
  );
  $("loraChannelNum").min = fields.channelNum.min;
  $("loraChannelNum").max = fields.channelNum.max;
  $("loraChannelNum").value = fields.channelNum.default;
  const frequency = fields.overrideFrequencyMhz;
  $("loraOverrideFreq").min = frequency.min;
  $("loraOverrideFreq").max = frequency.max;
  $("loraOverrideFreq").step = frequency.step;
  $("loraOverrideFreq").value = frequency.default;
  $("okToMqtt").checked = state.buildOptions.okToMqtt.default;
  renderTtlNotice();
}

function renderTtlNotice() {
  const days = state.buildOptions?.artifactTtlDays;
  if (!days) return;
  $("submitTtl").textContent = t("step7.ttl", { days });
}

// expires_at is only set once a build succeeds, so until then all we can promise
// is the window length. Rendered in the viewer's timezone: the server stores UTC
// and these links get shared across them.
function renderExpiry(expiresAt) {
  const deadline = expiresAt ? new Date(expiresAt) : null;
  if (deadline && !Number.isNaN(deadline.getTime())) {
    const date = deadline.toLocaleString(currentLang(), { dateStyle: "long", timeStyle: "short" });
    $("resultTtl").textContent = t("result.ttlUntil", { date });
    return;
  }
  const days = state.buildOptions?.artifactTtlDays;
  $("resultTtl").textContent = days ? t("result.ttl", { days }) : "";
}

function selectedFirmware() {
  return state.firmwares.find((item) => item.id === $("firmwareId").value) || null;
}

function selectedVersion() {
  const firmware = selectedFirmware();
  if (firmware?.versioning === "branch") return state.versions[0] || null;
  return state.versions.find((item) => item.tag === $("firmwareTag").value) || null;
}

// The x.y.z the version gates compare. For a tag it is the tag itself; a branch
// has no tag, so the server reads it from the branch's version.properties.
function selectedGateVersion() {
  return selectedVersion()?.version || $("firmwareTag").value;
}

function syncAdvancedAvailability() {
  const tag = selectedGateVersion();
  const options = state.buildOptions;
  state.codeOptionsAvailable = Boolean(options && versionAtLeast(tag, options.minFirmwareVersion));
  state.codeOptionsNative = Boolean(options && versionAtLeast(tag, options.nativeSinceFirmwareVersion));
  state.maxChannels = options && versionAtLeast(tag, options.eightChannelsSinceFirmwareVersion) ? 8 : 3;
  document.querySelectorAll(".code-option").forEach((el) => {
    el.hidden = !state.codeOptionsAvailable;
  });
  document.querySelectorAll(".patch-only").forEach((el) => {
    el.hidden = state.codeOptionsNative;
  });
  $("advancedUnavailable").hidden = state.codeOptionsAvailable;
  updateLongNameCounter();
  syncCustomLora();
}

function syncCustomLora() {
  const enabled = state.codeOptionsAvailable && $("customLoraEnabled").checked;
  $("customLoraFields").hidden = !enabled;
  $("modemPreset").disabled = enabled;
  $("presetDisabledHint").hidden = !enabled;
}

function wifiSupported() {
  // The device combo is built by loadDevices(), so #deviceId is absent during the
  // first render. Unknown device means unknown family, same as any other family
  // we have no entry for.
  const picker = $("deviceId");
  const family = picker ? state.deviceFamilies[picker.value] : null;
  return !family || WIFI_FAMILIES.has(family);
}

// Recomputed from both conditions every time: a control hidden because the board
// has no WiFi must come back when the user picks a board that does.
function syncWifiAvailability() {
  const supported = wifiSupported();
  const inTemplate = (key) => state.templateKeys.size === 0 || state.templateKeys.has(key);
  const controls = Array.from($("wifiPanel").querySelectorAll("[data-pref-key]"));
  for (const el of controls) {
    el.hidden = !supported || !inTemplate(el.dataset.prefKey);
  }
  // Firmware that has no WiFi keys at all: drop the panel. Board with no WiFi
  // radio: keep it, so the note explaining the missing fields stays visible.
  $("wifiPanel").hidden = !controls.some((el) => inTemplate(el.dataset.prefKey));
  $("wifiUnsupported").hidden = supported;
}

// A board the firmware cannot build yet: say why under the picker and keep the
// submit button off. The server refuses it too, for API clients.
function syncDeviceAvailability() {
  const picker = $("deviceId");
  const info = picker ? state.unavailableDevices[picker.value] : null;
  const hint = $("deviceUnavailable");
  hint.hidden = !info;
  if (info) {
    const firmware = selectedFirmware();
    const reason = t(`device.unavailable.${info.reason}`);
    hint.innerHTML = t("device.unavailableHint", {
      firmware: escapeHtml(firmware ? firmware.name : ""),
      reason: escapeHtml(reason === `device.unavailable.${info.reason}` ? info.reason : reason),
      issue: `<a href="${escapeHtml(info.issue)}" target="_blank" rel="noreferrer">${escapeHtml(info.issue.replace(/^https:\/\/github\.com\//, ""))}</a>`,
    });
  }
  $("submitBuild").disabled = Boolean(info);
}

// The Web Flasher's "Meshtastic UI" switch: only for boards whose firmware has a
// -tft build. Unticked and hidden for any other board, so it never leaks into a submit.
// Ticked by default each time such a board is picked, as the Web Flasher does;
// reloading the list for the same board (a version change) keeps the user's choice.
function syncMuiOption() {
  const picker = $("deviceId");
  const device = picker ? picker.value : "";
  const available = state.muiDevices.has(device);
  $("muiOption").hidden = !available;
  if (!available) {
    $("muiEnabled").checked = false;
    state.muiDefaultFor = null;
  } else if (state.muiDefaultFor !== device) {
    $("muiEnabled").checked = true;
    state.muiDefaultFor = device;
  }
}

// (?) buttons: hover and keyboard focus are pure CSS; a tap or click toggles the
// box so it also works on touch screens. A click elsewhere or Escape closes it.
function wireHelpTips() {
  // Centred on the (?) by default; near a screen edge, slide it back inside.
  const place = (help) => {
    const pop = help.querySelector(".help-pop");
    pop.style.setProperty("--help-shift", "0px");
    const rect = pop.getBoundingClientRect();
    const margin = 8;
    let shift = 0;
    if (rect.right > window.innerWidth - margin) shift = window.innerWidth - margin - rect.right;
    if (rect.left + shift < margin) shift = margin - rect.left;
    pop.style.setProperty("--help-shift", `${Math.round(shift)}px`);
  };
  for (const help of document.querySelectorAll(".help")) {
    help.addEventListener("mouseenter", () => place(help));
    help.addEventListener("focusin", () => place(help));
  }
  const closeAll = (except) => {
    for (const el of document.querySelectorAll(".help.open")) {
      if (el !== except) el.classList.remove("open");
    }
  };
  for (const button of document.querySelectorAll(".help-tip")) {
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const help = button.closest(".help");
      closeAll(help);
      place(help);
      help.classList.toggle("open");
    });
  }
  document.addEventListener("click", () => closeAll(null));
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    closeAll(null);
    // A key press makes the focused (?) match :focus-visible, which shows the box again.
    if (document.activeElement?.classList.contains("help-tip")) document.activeElement.blur();
  });
}

function syncFixedGps() {
  $("fixedGpsFields").hidden = !$("fixedGpsEnabled").checked;
}

function syncManagedMode() {
  const hasAdminKey = ["adminKey", "adminKey1", "adminKey2"].some((id) => $(id).value.trim() !== "");
  const checkbox = $("securityIsManaged");
  checkbox.disabled = !hasAdminKey;
  if (!hasAdminKey) checkbox.checked = false;
}

// Controls for keys the selected firmware template does not define are hidden; setPref drops them anyway.
function syncTemplateGatedControls() {
  for (const el of document.querySelectorAll("[data-pref-key]")) {
    el.hidden = state.templateKeys.size > 0 && !state.templateKeys.has(el.dataset.prefKey);
  }
  syncWifiAvailability();
}

// Split out because the build page needs the labels but none of the form wiring.
async function loadDeviceCatalog() {
  const { devices } = await fetchJson("/api/devices");
  state.deviceFamilies = Object.fromEntries(devices.map((device) => [device.id, device.family]));
  state.deviceLabels = Object.fromEntries(devices.map((device) => [device.id, device.label]));
  return devices;
}

// The boards of the selected firmware at the selected version: forks add their
// own, and older tags lack newer ones. Without a firmware yet (first paint), the
// static catalogue.
async function loadDevices() {
  const firmware = state.firmwares.length ? selectedFirmware() : null;
  const tag = $("firmwareTag").value;
  let devices;
  state.unavailableDevices = {};
  state.muiDevices = new Set();
  if (firmware && (tag || firmware.versioning === "branch")) {
    const params = new URLSearchParams({ firmware: firmware.id });
    if (tag) params.set("tag", tag);
    const requested = params.toString();
    state.devicesRequest = requested;
    devices = (await fetchJson(`/api/devices?${params}`)).devices;
    // A newer firmware/version switch has already asked for its own list.
    if (state.devicesRequest !== requested) return;
    for (const device of devices) {
      state.deviceFamilies[device.id] = device.family;
      state.deviceLabels[device.id] = device.label;
      if (device.unavailable) state.unavailableDevices[device.id] = device.unavailable;
      if (device.mui) state.muiDevices.add(device.id);
    }
  } else {
    devices = await loadDeviceCatalog();
  }
  const previous = $("deviceId")?.value;
  const keep = previous && devices.some((device) => device.id === previous);
  // Still listed, so users find the board and read why; never the default pick.
  const fallback = devices.find((device) => !device.unavailable) || devices[0];
  $("deviceCombo").innerHTML = comboHtml(
    devices.map((device) => ({
      value: device.id,
      label: device.unavailable ? `${device.label} (${t("device.unavailable")})` : device.label,
      className: device.unavailable ? "is-unavailable" : "",
    })),
    keep ? previous : fallback ? fallback.id : "",
    { valueAttrs: 'id="deviceId" name="deviceId"', placeholder: t("step1.devicePlaceholder") },
  );
  $("deviceId").addEventListener("change", syncWifiAvailability);
  $("deviceId").addEventListener("change", syncDeviceAvailability);
  $("deviceId").addEventListener("change", syncMuiOption);
  $("deviceId").addEventListener("change", updatePrefsPreview);
  syncDeviceAvailability();
  syncMuiOption();
  // The list arrives after the first render, so repaint with the real device.
  syncWifiAvailability();
  updatePrefsPreview();
}

// The catalogue of firmware sources (data/firmwares.json). The build page needs the
// names too, so this is split from the form wiring like loadDeviceCatalog().
async function loadFirmwareCatalog() {
  const { default: defaultId, firmwares } = await fetchJson("/api/firmwares");
  state.firmwares = firmwares;
  state.firmwareNames = Object.fromEntries(firmwares.map((item) => [item.id, item.name]));
  return defaultId;
}

async function loadFirmwares() {
  const defaultId = await loadFirmwareCatalog();
  $("firmwareId").innerHTML = state.firmwares
    .map(
      (item) =>
        `<option value="${escapeHtml(item.id)}" ${item.id === defaultId ? "selected" : ""}>${escapeHtml(item.name)}</option>`,
    )
    .join("");
  syncFirmwareRepoLink();
}

function syncFirmwareRepoLink() {
  const firmware = selectedFirmware();
  const link = $("firmwareRepo");
  link.textContent = firmware ? firmware.url.replace(/^https:\/\//, "") : "";
  link.href = firmware ? firmware.url : "#";
}

// Called on every firmware switch too: each firmware has its own tag list.
async function loadVersions(forceRefresh = false) {
  const firmware = selectedFirmware();
  if (!firmware) return;
  const select = $("firmwareTag");
  const requestedFirmware = firmware.id;
  setStatusKey(forceRefresh ? "status.refreshingTags" : "status.loadingTags");
  select.disabled = true;
  const params = new URLSearchParams({ firmware: firmware.id });
  if (forceRefresh) params.set("refresh", "1");
  const { versions } = await fetchJson(`/api/firmware-versions?${params}`);
  // The user may have switched firmware again while this was in flight.
  if ($("firmwareId").value !== requestedFirmware) return;
  if (!versions.length) {
    throw new Error(t("error.noVersions"));
  }
  state.versions = versions;
  renderVersionSelect();
  await onFirmwareTagChange();
  setStatusKey("status.ready");
}

function renderVersionSelect() {
  const firmware = selectedFirmware();
  const select = $("firmwareTag");
  const hint = $("firmwareBranchHint");
  if (firmware?.versioning === "branch") {
    // No releases to choose from: one disabled N/A entry, and the hint names
    // the commit the build will actually compile.
    const head = state.versions[0];
    select.innerHTML = `<option value="">${escapeHtml(t("step1.noVersion"))}</option>`;
    select.disabled = true;
    hint.textContent = t("step1.branchHint", {
      branch: firmware.branch,
      version: head?.version || "?",
      sha: (head?.sha || "").slice(0, 7),
    });
    hint.hidden = false;
    return;
  }
  const previous = select.value;
  select.innerHTML = state.versions
    .map((version) => `<option value="${escapeHtml(version.tag)}">${escapeHtml(version.tag)}</option>`)
    .join("");
  if (previous && state.versions.some((version) => version.tag === previous)) {
    select.value = previous;
  }
  select.disabled = false;
  hint.hidden = true;
}

async function onFirmwareChange() {
  syncFirmwareRepoLink();
  state.versions = [];
  $("firmwareTag").innerHTML = "";
  await loadVersions(false);
}

async function onFirmwareTagChange() {
  populateStaticSelects(selectedGateVersion());
  syncAdvancedAvailability();
  await Promise.all([loadTemplate(), loadDevices()]);
}

async function loadTemplate() {
  const firmware = selectedFirmware();
  const tag = $("firmwareTag").value;
  if (!firmware || (!tag && firmware.versioning !== "branch")) return;
  const params = new URLSearchParams({ firmware: firmware.id });
  if (tag) params.set("tag", tag);
  const response = await fetch(`/api/prefs-template?${params}`);
  if (!response.ok) {
    const payload = await response.json();
    throw new Error(payload.error || t("error.template"));
  }
  const template = await response.text();
  state.templateKeys = extractTemplateKeys(template);
  state.templateExamples = extractTemplateExamples(template);
  state.templateDefaults = extractTemplateDefaults(template);
  // A key the previous tag had may not exist in this one.
  state.extraPrefs = state.extraPrefs.filter((row) => !row.key || state.templateKeys.has(row.key));
  syncTemplateGatedControls();
  if (!state.channels.length) {
    state.channels = [defaultChannel()];
  }
  if (state.channels.length > state.maxChannels) {
    state.channels = state.channels.slice(0, state.maxChannels);
  }
  renderChannels();
  renderExtraPrefs();
}

function extractTemplateKeys(template) {
  return new Set(Array.from(template.matchAll(/"(USERPREFS_[A-Z0-9_]+)"\s*:/g), (match) => match[1]));
}

// The template documents a sample value for most keys; show it as the placeholder
// so the free-form section hints at the shape each key expects.
function extractTemplateExamples(template) {
  const examples = {};
  for (const match of template.matchAll(/"(USERPREFS_[A-Z0-9_]+)"\s*:\s*("(?:[^"\\]|\\.)*")/g)) {
    try {
      examples[match[1]] = JSON.parse(match[2]);
    } catch (error) {
      // A malformed sample is not worth failing the page over.
    }
  }
  return examples;
}

// The server merges the template's active (uncommented) entries under the user's
// values. Seeding the preview with them keeps it equal to what actually gets built
// instead of quietly gaining keys on the way.
function extractTemplateDefaults(template) {
  try {
    const stripped = template.replace(/^\s*\/\/.*$/gm, "");
    const parsed = JSON.parse(stripped);
    if (!parsed || typeof parsed !== "object") return {};
    return Object.fromEntries(
      Object.entries(parsed).filter(
        ([key, value]) => key.startsWith("USERPREFS_") && (typeof value === "string" || typeof value === "number"),
      ),
    );
  } catch (error) {
    return {};
  }
}

function shortPrefKey(key) {
  return key.replace(/^USERPREFS_/, "");
}

// The advanced options expand into macros of their own; those are owned by the
// LoRa and MQTT controls too, so they must not also appear as free-form keys.
function codeOptionMacroNames() {
  const spec = state.buildOptions;
  if (!spec) return [];
  return [
    spec.okToMqtt.macro,
    spec.okToMqtt.nativeMacro,
    spec.customLora.usePresetMacro,
    ...Object.values(spec.customLora.fields).map((field) => field.macro),
  ];
}

function isFormManagedKey(key) {
  return (
    FORM_MANAGED_KEYS.has(key) ||
    /^USERPREFS_CHANNEL_\d+_/.test(key) ||
    codeOptionMacroNames().includes(key)
  );
}

function availableExtraKeys(exceptIndex) {
  const taken = new Set(
    state.extraPrefs.filter((_row, index) => index !== exceptIndex).map((row) => row.key).filter(Boolean),
  );
  return Array.from(state.templateKeys)
    .filter((key) => !isFormManagedKey(key) && !taken.has(key))
    .sort();
}

function renderExtraPrefs() {
  $("extraRows").innerHTML = state.extraPrefs
    .map((row, index) => {
      const options = availableExtraKeys(index);
      if (row.key && !options.includes(row.key)) options.push(row.key);
      options.sort();
      return `
    <div class="extra-row" data-index="${index}">
      <label>
        ${escapeHtml(t("extra.key"))}
        ${comboHtml(
          options.map((key) => ({ value: key, label: shortPrefKey(key) })),
          row.key,
          { valueAttrs: 'data-field="key"', placeholder: t("extra.choose") },
        )}
      </label>
      <label>
        ${escapeHtml(t("extra.value"))}
        <input data-field="value" type="text" autocomplete="off" value="${escapeHtml(row.value)}"
          placeholder="${escapeHtml(state.templateExamples[row.key] || "")}">
      </label>
      <button class="btn btn-icon" type="button" data-action="remove-extra"
        aria-label="${escapeHtml(t("channel.remove"))}" title="${escapeHtml(t("channel.remove"))}">&times;</button>
    </div>`;
    })
    .join("");
  $("addExtraPref").disabled = !availableExtraKeys(-1).length;
  updatePrefsPreview();
}

function syncExtraFromInput(input) {
  const container = input.closest(".extra-row");
  if (!container) return;
  const row = state.extraPrefs[Number(container.dataset.index)];
  if (row) row[input.dataset.field] = input.value;
}

function channelMuteSupported() {
  return state.maxChannels === 8 || state.templateKeys.has("USERPREFS_CHANNEL_0_IS_MUTED");
}

// Meshtastic names the primary channel after the modem preset (LONG_FAST -> LongFast).
function presetChannelName() {
  const preset = $("modemPreset").value.split("_ModemPreset_")[1];
  if (!preset) return "LongFast";
  return preset
    .split("_")
    .map((part) => part.charAt(0) + part.slice(1).toLowerCase())
    .join("");
}

// Only renames while the name is still the one the preset produced, so a name the
// user typed is never overwritten.
function syncPresetChannelName() {
  const next = presetChannelName();
  const first = state.channels[0];
  if (first && first.name === state.presetChannelName && first.name !== next) {
    first.name = next;
    renderChannels();
  }
  state.presetChannelName = next;
}

function defaultChannel() {
  return {
    name: DEFAULT_CHANNEL_NAME,
    psk: "AQ==",
    precision: "14",
    downlink: true,
    uplink: true,
    muted: false,
  };
}

function renderChannels() {
  const withMute = channelMuteSupported();
  const canReorder = state.channels.length > 1;
  $("channelRows").innerHTML = state.channels.map((channel, index) => `
    <div class="channel-row" data-index="${index}">
      <button class="drag-handle" type="button" data-action="drag" ${canReorder ? "" : "disabled"}
        aria-label="${escapeHtml(t("channel.reorder"))}" title="${escapeHtml(t("channel.reorder"))}">⠿</button>
      <div class="channel-fields">
      <label>
        ${escapeHtml(t("channel.name"))}
        <input data-field="name" type="text" value="${escapeHtml(channel.name)}" autocomplete="off" required>
      </label>
      <label>
        ${escapeHtml(t("channel.psk"))}
        <input data-field="psk" type="text" value="${escapeHtml(channel.psk)}" autocomplete="off" placeholder="AQ==">
      </label>
      <label class="precision-cell">
        ${escapeHtml(t("channel.precision"))}
        <input data-field="precision" type="range" min="0" max="${PRECISION_STEPS.length - 1}"
          value="${precisionStepIndex(channel.precision)}">
        <small class="field-hint" data-precision-label>${escapeHtml(precisionLabel(channel.precision))}</small>
      </label>
      <div class="channel-flags">
        <label class="check-line">
          <input data-field="uplink" type="checkbox" ${channel.uplink ? "checked" : ""}>
          <span>${escapeHtml(t("channel.uplink"))}</span>
        </label>
        <label class="check-line">
          <input data-field="downlink" type="checkbox" ${channel.downlink ? "checked" : ""}>
          <span>${escapeHtml(t("channel.downlink"))}</span>
        </label>
      </div>
      ${withMute ? `
      <label class="check-line">
        <input data-field="muted" type="checkbox" ${channel.muted ? "checked" : ""}>
        <span>${escapeHtml(t("channel.muted"))}</span>
      </label>` : ""}
      <button class="btn btn-icon" type="button" data-action="remove" ${state.channels.length === 1 ? "disabled" : ""}
        aria-label="${escapeHtml(t("channel.remove"))}" title="${escapeHtml(t("channel.remove"))}">&times;</button>
      </div>
    </div>
  `).join("");
  $("addChannel").disabled = state.channels.length >= state.maxChannels;
  $("channelHint").textContent = t("step4.hint", { max: state.maxChannels });
  updatePrefsPreview();
}

function precisionStepIndex(precision) {
  const index = PRECISION_STEPS.indexOf(Number(precision));
  return index >= 0 ? index : DEFAULT_PRECISION_INDEX;
}

function syncChannelFromInput(input) {
  const row = input.closest(".channel-row");
  if (!row) return;
  const channel = state.channels[Number(row.dataset.index)];
  if (!channel) return;
  const field = input.dataset.field;
  if (field === "precision") {
    // The slider walks PRECISION_STEPS; the stored value stays the firmware one.
    channel.precision = String(PRECISION_STEPS[Number(input.value)]);
    const label = row.querySelector("[data-precision-label]");
    if (label) label.textContent = precisionLabel(channel.precision);
    return;
  }
  channel[field] = input.type === "checkbox" ? input.checked : input.value;
}

// Reordering channel 0 changes the primary channel, so the whole row order matters.
// Pointer events (not HTML5 drag) because they also work on touch screens.
let channelDrag = null;

function onChannelDragStart(event) {
  const handle = event.target.closest("[data-action='drag']");
  if (!handle || handle.disabled) return;
  const row = handle.closest(".channel-row");
  if (!row) return;
  event.preventDefault();
  handle.setPointerCapture(event.pointerId);
  row.classList.add("dragging");
  channelDrag = { row, pointerId: event.pointerId };
}

function onChannelDragMove(event) {
  if (!channelDrag || event.pointerId !== channelDrag.pointerId) return;
  const rows = Array.from($("channelRows").querySelectorAll(".channel-row"));
  const target = rows.find((row) => {
    if (row === channelDrag.row) return false;
    const box = row.getBoundingClientRect();
    return event.clientY >= box.top && event.clientY <= box.bottom;
  });
  if (!target) return;
  const box = target.getBoundingClientRect();
  const after = event.clientY > box.top + box.height / 2;
  target.parentNode.insertBefore(channelDrag.row, after ? target.nextSibling : target);
}

function onChannelDragEnd(event) {
  if (!channelDrag || event.pointerId !== channelDrag.pointerId) return;
  channelDrag.row.classList.remove("dragging");
  channelDrag = null;
  const order = Array.from(
    $("channelRows").querySelectorAll(".channel-row"),
    (row) => Number(row.dataset.index),
  );
  state.channels = order.map((index) => state.channels[index]);
  renderChannels();
}

function bytesToByteArray(bytes) {
  if (!bytes.length) return "{}";
  return `{ ${Array.from(bytes, (byte) => `0x${byte.toString(16).padStart(2, "0")}`).join(", ")} }`;
}

function base64ToBytes(value, label, expectedLength = null) {
  const trimmed = value.trim();
  if (!trimmed) return null;
  try {
    const binary = atob(trimmed);
    const bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0));
    const normalized = btoa(String.fromCharCode(...bytes)).replace(/=+$/, "");
    if (trimmed.replace(/=+$/, "") !== normalized) {
      throw new Error("not canonical");
    }
    if (expectedLength !== null && bytes.length !== expectedLength) {
      throw new Error("wrong length");
    }
    return bytes;
  } catch (error) {
    throw new Error(
      expectedLength === null
        ? t("error.base64", { label })
        : t("error.base64Length", { label, bytes: expectedLength }),
    );
  }
}

function setPref(prefs, key, value) {
  if (!state.templateKeys.size || state.templateKeys.has(key) || isExtraChannelKey(key)) {
    prefs[key] = value;
  }
}

// Firmware >= 2.8.0 reads channels 0..7 even though the template only documents the first three.
function isExtraChannelKey(key) {
  return state.maxChannels === 8 && /^USERPREFS_CHANNEL_[0-7]_[A-Z_]+$/.test(key);
}

function setOptionalPref(prefs, key, rawValue) {
  const value = String(rawValue).trim();
  if (value !== "") setPref(prefs, key, value);
}

// Only on submit: the preview runs on every keystroke and from page load, when
// both fields are still empty.
function validateOwnerNames() {
  let first = null;
  for (const id of ["longName", "shortName"]) {
    const input = $(id);
    const empty = input.value.trim() === "";
    input.classList.toggle("fieldError", empty);
    if (empty && !first) first = input;
  }
  if (first) {
    first.focus();
    throw new Error(t("error.ownerNames"));
  }
}

// Firmware 2.8.0 keeps only 24 bytes of the long name (39 before) and turns a
// character cut in half into "?", so the limit follows the selected version.
function longNameMaxBytes() {
  const spec = state.buildOptions?.longName;
  if (!spec) return 24;
  return versionAtLeast(selectedGateVersion(), spec.sinceFirmwareVersion) ? spec.maxBytes : spec.legacyMaxBytes;
}

function updateLongNameCounter() {
  const input = $("longName");
  const max = longNameMaxBytes();
  const byteLength = encoder.encode(input.value).length;
  $("longNameBytes").textContent = `${byteLength}/${max} bytes`;
  // Only add or clear the over-limit mark: an empty name keeps the "required" mark from a failed submit.
  if (byteLength > max) input.classList.add("fieldError");
  else if (input.value.trim()) input.classList.remove("fieldError");
  return { byteLength, max };
}

function validateLongName() {
  const { byteLength, max } = updateLongNameCounter();
  if (byteLength > max) {
    throw new Error(t("error.longName", { bytes: max }));
  }
}

function validateShortName() {
  const input = $("shortName");
  const byteLength = encoder.encode(input.value).length;
  $("shortNameBytes").textContent = `${byteLength}/4 bytes`;
  input.classList.toggle("fieldError", byteLength > 4);
  if (byteLength > 4) {
    throw new Error(t("error.shortName"));
  }
}

// bin/platformio-custom.py only quotes a value that does not already look like a
// number, bool, enum, hex or byte array, so these would reach the compiler bare.
function validateCompilesAsString(value, label) {
  const looksUnquoted =
    value.startsWith("{") ||
    /^-?[\d.]+$/.test(value) ||
    /^0[xX][0-9a-fA-F]+$/.test(value) ||
    value === "true" ||
    value === "false" ||
    value.startsWith("meshtastic_");
  if (looksUnquoted) {
    throw new Error(t("error.mustBeText", { label }));
  }
  return value;
}

// Six digits, first one not 0. A leading 0 is compiled as an octal number, and
// on nRF52 the firmware only accepts a passkey of exactly six characters.
function validateBlePin() {
  const input = $("blePin");
  const value = input.value.trim();
  const valid = value === "" || /^[1-9]\d{5}$/.test(value);
  input.classList.toggle("fieldError", !valid);
  if (!valid) {
    throw new Error(t("error.blePin"));
  }
  return value;
}

function validateMaxBytes(value, label, maxBytes) {
  if (encoder.encode(value).length > maxBytes) {
    throw new Error(t("error.maxBytes", { label, bytes: maxBytes }));
  }
  return value;
}

function validateChannel(channel, index) {
  const precision = Number(channel.precision);
  if (!channel.name.trim()) {
    throw new Error(t("error.channelName", { n: index + 1 }));
  }
  if (!Number.isInteger(precision) || precision < 0 || precision > 32) {
    throw new Error(t("error.channelPrecision", { n: index + 1 }));
  }
  return {
    name: channel.name.trim(),
    pskBytes: base64ToBytes(channel.psk, t("label.channelKey", { n: index + 1 })),
    precision: String(precision),
  };
}

function buildPrefs() {
  validateLongName();
  validateShortName();
  const prefs = {};
  for (const [key, value] of Object.entries(state.templateDefaults)) {
    prefs[key] = String(value);
  }

  // No default names: the form used to prefill them and many nodes went out
  // as "Mi nodo Meshtastic". Empty stays out of the preview; submitting
  // requires both (validateOwnerNames).
  setOptionalPref(prefs, "USERPREFS_CONFIG_OWNER_LONG_NAME", $("longName").value);
  setOptionalPref(prefs, "USERPREFS_CONFIG_OWNER_SHORT_NAME", $("shortName").value);
  setPref(prefs, "USERPREFS_CONFIG_LORA_REGION", $("loraRegion").value);
  setPref(prefs, "USERPREFS_CONFIG_DEVICE_ROLE", $("deviceRole").value);
  setPref(prefs, "USERPREFS_LORACONFIG_MODEM_PRESET", $("modemPreset").value);
  setPref(prefs, "USERPREFS_TZ_STRING", $("tzString").value.trim());
  setOptionalPref(prefs, "USERPREFS_LORACONFIG_TX_POWER", $("loraTxPower").value);

  setPref(prefs, "USERPREFS_CONFIG_DEVICE_REBROADCAST_MODE", $("rebroadcastMode").value);
  setOptionalPref(prefs, "USERPREFS_CONFIG_DEVICE_NODE_INFO_BROADCAST_SECS", $("nodeInfoSecs").value);
  setOptionalPref(prefs, "USERPREFS_CONFIG_DEVICE_TELEM_UPDATE_INTERVAL", $("deviceTelemInterval").value);

  const mqttAddress = $("mqttAddress").value.trim();
  if (mqttAddress) {
    validateMaxBytes(mqttAddress, t("label.mqttAddress"), 61);
    setPref(prefs, "USERPREFS_MQTT_ADDRESS", `'${mqttAddress.replace(/'/g, "")}'`);
  }
  if ($("mqttEnabled").checked) {
    setPref(prefs, "USERPREFS_MQTT_ENABLED", "1");
  }
  const mqttUsername = $("mqttUsername").value.trim();
  if (mqttUsername) {
    setPref(prefs, "USERPREFS_MQTT_USERNAME", validateMaxBytes(mqttUsername, t("label.mqttUsername"), 63));
  }
  const mqttPassword = $("mqttPassword").value;
  if (mqttPassword) {
    setPref(prefs, "USERPREFS_MQTT_PASSWORD", validateMaxBytes(mqttPassword, t("label.mqttPassword"), 31));
  }
  const mqttRoot = $("mqttRootTopic").value.trim();
  if (mqttRoot) {
    setPref(prefs, "USERPREFS_MQTT_ROOT_TOPIC", validateMaxBytes(mqttRoot, t("label.mqttRoot"), 31));
  }
  setPref(prefs, "USERPREFS_CONFIG_LORA_IGNORE_MQTT", String($("ignoreMqtt").checked));
  if (okToMqttIsPlainPref()) {
    setPref(prefs, state.buildOptions.okToMqtt.nativeMacro, String($("okToMqtt").checked));
  }

  setPref(prefs, "USERPREFS_CONFIG_GPS_MODE", $("gpsMode").value);
  setOptionalPref(prefs, "USERPREFS_CONFIG_GPS_UPDATE_INTERVAL", $("gpsUpdateInterval").value);
  setOptionalPref(prefs, "USERPREFS_CONFIG_POSITION_BROADCAST_INTERVAL", $("positionBroadcastInterval").value);
  setPref(prefs, "USERPREFS_CONFIG_SMART_POSITION_ENABLED", String($("smartPosition").checked));
  if ($("blockPositionOnEvent").checked) {
    setPref(prefs, "USERPREFS_BLOCK_POSITION_ON_EVENT_CHANNEL", "1");
  }
  if ($("fixedGpsEnabled").checked) {
    // The firmware only tests #ifdef, so the flag carries no value of its own.
    setPref(prefs, "USERPREFS_FIXED_GPS", "");
    setOptionalPref(prefs, "USERPREFS_FIXED_GPS_LAT", $("fixedGpsLat").value);
    setOptionalPref(prefs, "USERPREFS_FIXED_GPS_LON", $("fixedGpsLon").value);
    setOptionalPref(prefs, "USERPREFS_FIXED_GPS_ALT", $("fixedGpsAlt").value);
  }

  // Empty PIN: no key at all, so the firmware keeps its own pairing default.
  setOptionalPref(prefs, "USERPREFS_FIXED_BLUETOOTH", validateBlePin());
  // A board with no WiFi radio gets no WiFi macros, whatever is still typed in the form.
  if (wifiSupported()) {
    buildWifiPrefs(prefs);
  }

  setPref(prefs, "USERPREFS_MQTT_ENCRYPTION_ENABLED", String($("mqttEncryption").checked));
  setPref(prefs, "USERPREFS_MQTT_TLS_ENABLED", String($("mqttTls").checked));

  [
    ["adminKey", "USERPREFS_USE_ADMIN_KEY_0", t("label.adminKey")],
    ["adminKey1", "USERPREFS_USE_ADMIN_KEY_1", t("label.adminKey1")],
    ["adminKey2", "USERPREFS_USE_ADMIN_KEY_2", t("label.adminKey2")],
  ].forEach(([id, key, label]) => {
    const bytes = base64ToBytes($(id).value, label, 32);
    if (bytes) setPref(prefs, key, bytesToByteArray(bytes));
  });
  setPref(prefs, "USERPREFS_CONFIG_SECURITY_PACKET_SIGNATURE_POLICY", $("signaturePolicy").value);
  if ($("securityIsManaged").checked) {
    setPref(prefs, "USERPREFS_CONFIG_SECURITY_IS_MANAGED", "true");
  }

  setPref(prefs, "USERPREFS_CHANNELS_TO_WRITE", String(state.channels.length));
  const withMute = channelMuteSupported();
  state.channels.forEach((channel, index) => {
    const valid = validateChannel(channel, index);
    setPref(prefs, `USERPREFS_CHANNEL_${index}_NAME`, valid.name);
    setPref(prefs, `USERPREFS_CHANNEL_${index}_PRECISION`, valid.precision);
    if (valid.pskBytes) {
      setPref(prefs, `USERPREFS_CHANNEL_${index}_PSK`, bytesToByteArray(valid.pskBytes));
    }
    setPref(prefs, `USERPREFS_CHANNEL_${index}_DOWNLINK_ENABLED`, String(Boolean(channel.downlink)));
    setPref(prefs, `USERPREFS_CHANNEL_${index}_UPLINK_ENABLED`, String(Boolean(channel.uplink)));
    if (withMute) {
      setPref(prefs, `USERPREFS_CHANNEL_${index}_IS_MUTED`, String(Boolean(channel.muted)));
    }
  });

  for (const row of state.extraPrefs) {
    const value = row.value.trim();
    if (row.key && value) setPref(prefs, row.key, value);
  }

  return prefs;
}

function buildWifiPrefs(prefs) {
  if ($("wifiEnabled").checked) {
    setPref(prefs, "USERPREFS_NETWORK_WIFI_ENABLED", "true");
  }
  const ssid = $("wifiSsid").value.trim();
  if (ssid) {
    validateMaxBytes(ssid, t("label.wifiSsid"), 32);
    setPref(prefs, "USERPREFS_NETWORK_WIFI_SSID", validateCompilesAsString(ssid, t("label.wifiSsid")));
  }
  const psk = $("wifiPsk").value;
  if (psk) {
    validateMaxBytes(psk, t("label.wifiPsk"), 64);
    setPref(prefs, "USERPREFS_NETWORK_WIFI_PSK", validateCompilesAsString(psk, t("label.wifiPsk")));
  }
}

// Below nativeSinceFirmwareVersion the macro only exists because the builder patches
// NodeDB, so it stays a code option there.
function okToMqttIsPlainPref() {
  return Boolean(
    state.codeOptionsNative &&
      state.buildOptions &&
      state.templateKeys.has(state.buildOptions.okToMqtt.nativeMacro),
  );
}

function buildCodeOptions() {
  if (!state.codeOptionsAvailable) return null;
  const options = okToMqttIsPlainPref() ? {} : { okToMqtt: $("okToMqtt").checked };
  if ($("customLoraEnabled").checked) {
    options.customLora = {
      bandwidthKhz: Number($("loraBandwidth").value),
      spreadFactor: Number($("loraSpreadFactor").value),
      codingRate: Number($("loraCodingRate").value),
      channelNum: Number($("loraChannelNum").value),
      overrideFrequencyMhz: Number($("loraOverrideFreq").value),
    };
  }
  return options;
}

// Stroke paths for a 24x24 viewBox, drawn with currentColor so .build-status
// can tint them per state. Emoji render differently on every platform, and the
// build page is mostly read on phones.
const STATUS_ICONS = {
  queued: '<circle cx="12" cy="12" r="9"/><path d="M12 7.5V12l3 1.8"/>',
  running: '<path d="M12 3a9 9 0 1 0 9 9"/><path d="M12 7.5V12l3 1.8"/>',
  succeeded: '<circle cx="12" cy="12" r="9"/><path d="m7.8 12.2 2.9 2.9 5.5-6.2"/>',
  failed: '<circle cx="12" cy="12" r="9"/><path d="M12 7.2v5.4"/><path d="M12 16.2v.6"/>',
  expired: '<circle cx="12" cy="12" r="9"/><path d="M12 7.5V12l3 1.8"/><path d="m5.6 5.6 12.8 12.8"/>',
};

function statusIconHtml(status) {
  return (
    `<svg class="status-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" ` +
    `stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${STATUS_ICONS[status]}</svg>`
  );
}

function renderBuildStatus(status, queue = null) {
  const el = $("buildStatus");
  // The column is CHECK-constrained server side, but this string ends up in a
  // class name and next to innerHTML, so only render states we know.
  const known = Object.hasOwn(STATUS_ICONS, status) ? status : "queued";
  el.dataset.state = known;
  const detail = queueDetail(known, queue);
  el.innerHTML =
    `${statusIconHtml(known)}<span>${escapeHtml(t(`buildStatus.${known}`))}</span>` +
    (detail ? `<span class="queue-info">${escapeHtml(detail)}</span>` : "");
}

// "~25 min", "~1 h 05 min", "<1 min". Rounded up: an estimate that runs out
// before the build does reads worse than one that is a minute pessimistic.
function formatDuration(seconds) {
  const minutes = Math.ceil(seconds / 60);
  if (minutes < 1) return t("queue.underMinute");
  if (minutes < 60) return `~${minutes} min`;
  const hours = Math.floor(minutes / 60);
  return `~${hours} h ${String(minutes % 60).padStart(2, "0")} min`;
}

// Nothing for a build with nobody ahead: the worker picks it up within seconds.
// No time when the server says the queue looks stuck (remainingSeconds null).
function queueDetail(status, queue) {
  if (!queue || typeof queue !== "object") return "";
  const remaining = Number.isFinite(queue.remainingSeconds) ? queue.remainingSeconds : null;
  if (status === "queued") {
    const ahead = Number.isInteger(queue.ahead) ? queue.ahead : 0;
    if (ahead < 1) return "";
    const parts = [t(ahead === 1 ? "queue.aheadOne" : "queue.ahead", { n: ahead })];
    if (remaining !== null) parts.push(t("queue.readyIn", { time: formatDuration(remaining) }));
    return parts.join(" · ");
  }
  if (status === "running") {
    if (queue.overrun) return t("queue.overrun");
    if (remaining !== null) return t("queue.remaining", { time: formatDuration(remaining) });
  }
  return "";
}

// The advanced options are not userPrefs keys: the server expands them into these
// macros and merges them after the user overrides. Show them so the preview is honest.
function codeOptionMacros() {
  const options = buildCodeOptions();
  const spec = state.buildOptions;
  if (!options || !spec) return [];
  const macros = [];
  if (options.okToMqtt !== undefined) {
    macros.push([state.codeOptionsNative ? spec.okToMqtt.nativeMacro : spec.okToMqtt.macro, String(options.okToMqtt)]);
  }
  if (options.customLora) {
    macros.push([spec.customLora.usePresetMacro, "false"]);
    for (const [name, field] of Object.entries(spec.customLora.fields)) {
      macros.push([field.macro, String(options.customLora[name])]);
    }
  }
  return macros;
}

// The preview follows the order of the form so a key is easy to find, with the
// keys nobody chose (this firmware's own defaults) last.
function previewGroups(prefs) {
  const nativeOkToMqtt = state.buildOptions ? state.buildOptions.okToMqtt.nativeMacro : null;
  const ordered = [
    ["step2.title", ["USERPREFS_CONFIG_OWNER_LONG_NAME", "USERPREFS_CONFIG_OWNER_SHORT_NAME", "USERPREFS_TZ_STRING"]],
    [
      "step3.title",
      [
        "USERPREFS_CONFIG_LORA_REGION",
        "USERPREFS_LORACONFIG_MODEM_PRESET",
        "USERPREFS_LORACONFIG_TX_POWER",
        "USERPREFS_CONFIG_LORA_IGNORE_MQTT",
        nativeOkToMqtt,
      ],
    ],
    [
      "behaviour.title",
      [
        "USERPREFS_CONFIG_DEVICE_ROLE",
        "USERPREFS_CONFIG_DEVICE_REBROADCAST_MODE",
        "USERPREFS_CONFIG_DEVICE_NODE_INFO_BROADCAST_SECS",
        "USERPREFS_CONFIG_DEVICE_TELEM_UPDATE_INTERVAL",
      ],
    ],
    [
      "step4.title",
      ["USERPREFS_CHANNELS_TO_WRITE", ...Object.keys(prefs).filter((key) => /^USERPREFS_CHANNEL_\d+_/.test(key)).sort()],
    ],
    [
      "step5.mqttHead",
      [
        "USERPREFS_MQTT_ENABLED",
        "USERPREFS_MQTT_ADDRESS",
        "USERPREFS_MQTT_USERNAME",
        "USERPREFS_MQTT_PASSWORD",
        "USERPREFS_MQTT_ROOT_TOPIC",
        "USERPREFS_MQTT_ENCRYPTION_ENABLED",
        "USERPREFS_MQTT_TLS_ENABLED",
      ],
    ],
    [
      "radios.title",
      [
        "USERPREFS_FIXED_BLUETOOTH",
        "USERPREFS_NETWORK_WIFI_ENABLED",
        "USERPREFS_NETWORK_WIFI_SSID",
        "USERPREFS_NETWORK_WIFI_PSK",
      ],
    ],
    [
      "position.title",
      [
        "USERPREFS_CONFIG_GPS_MODE",
        "USERPREFS_CONFIG_GPS_UPDATE_INTERVAL",
        "USERPREFS_CONFIG_POSITION_BROADCAST_INTERVAL",
        "USERPREFS_CONFIG_SMART_POSITION_ENABLED",
        "USERPREFS_BLOCK_POSITION_ON_EVENT_CHANNEL",
        "USERPREFS_FIXED_GPS",
        "USERPREFS_FIXED_GPS_LAT",
        "USERPREFS_FIXED_GPS_LON",
        "USERPREFS_FIXED_GPS_ALT",
      ],
    ],
    [
      "security.title",
      [
        "USERPREFS_USE_ADMIN_KEY_0",
        "USERPREFS_USE_ADMIN_KEY_1",
        "USERPREFS_USE_ADMIN_KEY_2",
        "USERPREFS_CONFIG_SECURITY_PACKET_SIGNATURE_POLICY",
        "USERPREFS_CONFIG_SECURITY_IS_MANAGED",
      ],
    ],
    ["extra.title", state.extraPrefs.map((row) => row.key).filter(Boolean)],
  ];

  const groups = [];
  const placed = new Set();
  for (const [label, keys] of ordered) {
    const entries = [];
    for (const key of keys) {
      if (!key || placed.has(key) || !(key in prefs)) continue;
      placed.add(key);
      entries.push([key, prefs[key]]);
    }
    if (entries.length) groups.push({ label: t(label), entries });
  }
  const leftover = Object.keys(prefs).filter((key) => !placed.has(key)).sort();
  if (leftover.length) {
    groups.push({ label: t("preview.defaults"), entries: leftover.map((key) => [key, prefs[key]]) });
  }
  return groups;
}

function prefsPreviewText(prefs) {
  const groups = previewGroups(prefs);
  const total = groups.reduce((count, group) => count + group.entries.length, 0);
  const lines = ["{"];
  let written = 0;
  for (const group of groups) {
    if (written) lines.push("");
    lines.push(`  // ${group.label}`);
    for (const [key, value] of group.entries) {
      written += 1;
      lines.push(`  ${JSON.stringify(key)}: ${JSON.stringify(String(value))}${written < total ? "," : ""}`);
    }
  }
  const macros = codeOptionMacros();
  if (macros.length) {
    lines.push("");
    lines.push(`  // ${t("preview.injected")}`);
    for (const [key, value] of macros) {
      lines.push(`  // ${JSON.stringify(key)}: ${JSON.stringify(value)}`);
    }
  }
  lines.push("}");
  return `${lines.join("\n")}\n`;
}

function updatePrefsPreview() {
  try {
    syncManagedMode();
    syncFixedGps();
    const prefs = buildPrefs();
    $("prefsJsonc").value = prefsPreviewText(prefs);
    if (state.statusIsError) {
      setStatusKey("status.ready");
    }
    return true;
  } catch (error) {
    setStatus(error.message, true);
    return false;
  }
}

async function submitBuild(event) {
  event.preventDefault();
  if (!updatePrefsPreview()) return;
  try {
    validateOwnerNames();
  } catch (error) {
    setStatus(error.message, true);
    return;
  }
  if (state.unavailableDevices[$("deviceId").value]) return;
  $("submitBuild").disabled = true;
  try {
    setStatusKey("status.creating");
    const payload = {
      deviceId: $("deviceId").value,
      firmwareId: $("firmwareId").value,
      prefsJsonc: $("prefsJsonc").value,
    };
    if (selectedFirmware()?.versioning !== "branch") {
      payload.firmwareTag = $("firmwareTag").value;
    }
    if (!$("muiOption").hidden && $("muiEnabled").checked) {
      payload.mui = true;
    }
    const codeOptions = buildCodeOptions();
    if (codeOptions) {
      payload.codeOptions = codeOptions;
    }
    const result = await fetchJson("/api/builds", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    history.replaceState(null, "", `/build/${encodeURIComponent(result.build.token)}`);
    state.lastQueue = result.queue ?? null;
    showBuild(result.build, result.downloadUrl, result.buildUrl);
    startPolling(result.build.token);
    setStatusKey("status.queued");
  } catch (error) {
    setStatus(error.message, true);
  } finally {
    $("submitBuild").disabled = Boolean(state.unavailableDevices[$("deviceId").value]);
  }
}

// "Jentastic v2.8.104", or for a branch "Nodastic nodastic @ daf3a61".
function describeBuildFirmware(build) {
  const name = state.firmwareNames?.[build.firmwareId] || build.firmwareId || "";
  const firmware = state.firmwares.find((item) => item.id === build.firmwareId);
  const ref =
    firmware?.versioning === "branch"
      ? `${build.firmwareTag} @ ${String(build.firmwareSha || "").slice(0, 7)}`
      : build.firmwareTag;
  return name ? `${name} ${ref}` : ref;
}

function showBuild(build, downloadUrl = null, buildUrl = null) {
  state.lastBuild = build;
  if (downloadUrl) state.lastDownloadUrl = downloadUrl;
  if (buildUrl) state.lastBuildUrl = buildUrl;
  $("result").hidden = false;
  renderBuildStatus(build.status, state.lastQueue);
  $("buildNode").textContent = build.ownerLongName || "-";
  $("buildShortName").textContent = build.ownerShortName || "-";
  $("buildDevice").textContent = build.deviceLabel || state.deviceLabels?.[build.deviceId] || build.deviceId;
  $("buildFirmware").textContent = describeBuildFirmware(build);

  renderExpiry(build.expiresAt);

  const url = state.lastBuildUrl || `${location.origin}/build/${build.token}`;
  $("buildUrl").textContent = url;
  $("buildUrl").href = url;

  renderBuildFailure(build);

  const link = $("downloadLink");
  if (build.status === "succeeded") {
    link.textContent = t("result.downloadZip");
    link.href = state.lastDownloadUrl || `/download/${build.token}`;
  } else if (build.status === "failed") {
    link.textContent = t("result.failed");
    link.removeAttribute("href");
  } else if (build.status === "expired") {
    link.textContent = t("result.expired");
    link.removeAttribute("href");
  } else {
    link.textContent = t("result.pending");
    link.removeAttribute("href");
  }
}

// The server sends a stable reason code plus at most one quoted line from the
// build log. The code is what gets translated; the detail line stays verbatim
// because it is a compiler diagnostic and translating it would help nobody.
function renderBuildFailure(build) {
  const panel = $("buildFailure");
  if (build.status !== "failed") {
    panel.hidden = true;
    return;
  }
  const code = build.errorCode || "unknown";
  // A code this page does not know about still renders as a real sentence.
  const known = t(`buildError.${code}`) !== `buildError.${code}`;
  const key = known ? code : "unknown";
  $("buildFailureReason").textContent = t(`buildError.${key}`);
  $("buildFailureHint").textContent = t(`buildError.${key}Hint`);
  const detail = $("buildFailureDetail");
  if (build.error) {
    detail.textContent = `${t("buildError.detail")}: ${build.error}`;
    detail.hidden = false;
  } else {
    detail.textContent = "";
    detail.hidden = true;
  }
  panel.hidden = false;
}

function startPolling(token) {
  state.currentBuildToken = token;
  if (state.pollTimer) clearInterval(state.pollTimer);
  state.pollTimer = setInterval(async () => {
    try {
      const { build, queue } = await fetchJson(`/api/builds/${token}`);
      state.lastQueue = queue ?? null;
      showBuild(build);
      // A dropped poll is normal on a phone or while a build pins the host, and
      // without this the error sticks for good while polling carries on fine.
      if (state.statusIsError) setStatusKey("status.ready");
      if (["succeeded", "failed", "expired"].includes(build.status)) {
        clearInterval(state.pollTimer);
      }
    } catch (error) {
      setStatus(error.message, true);
    }
  }, 5000);
}

async function loadExistingBuild(token) {
  setStatusKey("status.loadingBuild");
  const { build, queue } = await fetchJson(`/api/builds/${encodeURIComponent(token)}`);
  state.lastQueue = queue ?? null;
  showBuild(build);
  if (!["succeeded", "failed", "expired"].includes(build.status)) {
    startPolling(build.token);
  }
  setStatusKey("status.ready");
}

function bindEvents() {
  $("buildForm").addEventListener("submit", submitBuild);
  $("firmwareId").addEventListener("change", () => {
    onFirmwareChange().catch((error) => setStatus(error.message, true));
  });
  $("firmwareTag").addEventListener("change", () => {
    onFirmwareTagChange().catch((error) => setStatus(error.message, true));
  });
  // Clear the "required" mark from a failed submit as soon as there is a name.
  $("longName").addEventListener("input", () => {
    if ($("longName").value.trim()) $("longName").classList.remove("fieldError");
    updateLongNameCounter();
  });
  $("customLoraEnabled").addEventListener("change", syncCustomLora);
  wireHelpTips();
  $("modemPreset").addEventListener("change", syncPresetChannelName);
  $("copyBuildUrl").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText($("buildUrl").textContent);
      setStatusKey("result.copied");
    } catch (error) {
      setStatus(error.message, true);
    }
  });
  $("addChannel").addEventListener("click", () => {
    if (state.channels.length >= state.maxChannels) return;
    state.channels.push({
      ...defaultChannel(),
      name: `${t("channel.defaultName")} ${state.channels.length + 1}`,
    });
    renderChannels();
  });
  $("channelRows").addEventListener("input", (event) => {
    if (!(event.target instanceof HTMLInputElement)) return;
    syncChannelFromInput(event.target);
    updatePrefsPreview();
  });
  $("channelRows").addEventListener("change", (event) => {
    if (!(event.target instanceof HTMLInputElement)) return;
    syncChannelFromInput(event.target);
    updatePrefsPreview();
  });
  $("channelRows").addEventListener("pointerdown", onChannelDragStart);
  $("channelRows").addEventListener("pointermove", onChannelDragMove);
  $("channelRows").addEventListener("pointerup", onChannelDragEnd);
  $("channelRows").addEventListener("pointercancel", onChannelDragEnd);
  $("channelRows").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-action='remove']");
    if (!button) return;
    state.channels.splice(Number(button.closest(".channel-row").dataset.index), 1);
    renderChannels();
  });
  $("addExtraPref").addEventListener("click", () => {
    state.extraPrefs.push({ key: "", value: "" });
    renderExtraPrefs();
  });
  $("extraRows").addEventListener("change", (event) => {
    if (!event.target.matches(".combo-value[data-field]")) return;
    syncExtraFromInput(event.target);
    renderExtraPrefs();
  });
  $("extraRows").addEventListener("input", (event) => {
    if (!event.target.matches("input[data-field]")) return;
    syncExtraFromInput(event.target);
    updatePrefsPreview();
  });
  $("extraRows").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-action='remove-extra']");
    if (!button) return;
    state.extraPrefs.splice(Number(button.closest(".extra-row").dataset.index), 1);
    renderExtraPrefs();
  });
  document.querySelectorAll("input, select").forEach((input) => {
    if (input.closest("#channelRows") || input.closest("#extraRows")) return;
    if (input.classList.contains("combo-input")) return;
    input.addEventListener("input", updatePrefsPreview);
    input.addEventListener("change", updatePrefsPreview);
  });
  document.querySelectorAll("[data-tz]").forEach((button) => {
    button.addEventListener("click", () => {
      $("tzString").value = button.dataset.tz;
      updatePrefsPreview();
    });
  });
  document.querySelectorAll("[data-lang]").forEach((button) => {
    button.addEventListener("click", () => setLang(button.dataset.lang));
  });
  document.addEventListener("languagechange", () => {
    if (!state.buildViewOnly && state.versions.length) renderVersionSelect();
    if (!state.buildViewOnly && Object.keys(state.unavailableDevices).length) loadDevices();
    renderTtlNotice();
    renderExtraPrefs();
    renderChannels();
    if (state.statusKey) setStatusKey(state.statusKey);
    if (state.lastBuild) showBuild(state.lastBuild);
  });
}

applyI18n();
skinSelects();
populateStaticSelects();
bindEvents();
bindCombos();
state.channels = [defaultChannel()];
renderChannels();

const buildViewToken = decodeURIComponent(/^\/build\/([^/]+)\/?$/.exec(location.pathname)?.[1] ?? "");

if (buildViewToken) {
  // Permalink view: only the header, the build panel and the footer. The status
  // line lives inside the form, so move it out before hiding it or a failed
  // lookup would have nowhere to report. Devices and firmware tags are form-only
  // data, and loadVersions() hits GitHub, so neither is worth loading here.
  state.buildViewOnly = true;
  document.querySelector(".app-main").prepend($("statusText"));
  $("buildForm").hidden = true;
  // Swap the keys rather than the text: applyI18n() re-reads them on every
  // language switch, so "Request created" would come back otherwise.
  $("resultTitle").dataset.i18n = "result.titleView";
  $("resultKeep").dataset.i18n = "result.keepView";
  applyI18n();
  Promise.all([loadBuildOptions(), loadDeviceCatalog(), loadFirmwareCatalog()])
    .then(() => loadExistingBuild(buildViewToken))
    .catch((error) => setStatus(error.message, true));
} else {
  Promise.all([loadDevices(), loadBuildOptions(), loadFirmwares()])
    .then(() => loadVersions(false))
    .catch((error) => setStatus(error.message, true));
}
