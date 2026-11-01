const DICT = {
  es: {
    "page.title": "Meshtastic Builder",
    "header.tagline": "Firmware Meshtastic a medida, sin editar JSON a mano",
    "footer.trademark":
      "Meshtastic es una marca registrada de Meshtastic LLC. Este proyecto no esta afiliado ni respaldado por Meshtastic LLC, ni por ninguna de las marcas de los dispositivos listados. Es un proyecto hecho por aficion.",
    "footer.source":
      "<a href=\"https://github.com/lazynoda/meshtastic-builder\" target=\"_blank\" rel=\"noreferrer\">Codigo fuente</a> bajo licencia AGPL-3.0.",

    "step1.title": "Firmware y dispositivo",
    "step1.device": "Dispositivo",
    "step1.mui": "Meshtastic UI",
    "help.label": "Ayuda",
    "step1.muiHint": "Compila la variante con Meshtastic UI (MUI), la interfaz tactil para la pantalla de la placa. Es lo mismo que el interruptor del Web Flasher.",
    "step1.devicePlaceholder": "Busca un dispositivo",
    "step1.firmware": "Firmware",
    "step1.version": "Version de firmware",
    "step1.noVersion": "N/A",
    "step1.branchHint": "Sin versiones: se compila la rama {branch} ({version}, {sha}).",
    "device.unavailable": "no disponible",
    "device.unavailableHint": "No disponible con {firmware} por ahora: {reason}. Estamos trabajando en ello ({issue}). Mientras tanto puedes compilarlo con Meshtastic Oficial.",
    "device.unavailable.firmware_too_big": "el firmware no cabe en la memoria flash de esta placa",
    "device.unavailableFixedHint": "No disponible con {firmware} {version}: {reason}. Funciona desde {firmware} {tag}.",
    "device.unavailableComingHint":
      "No disponible con {firmware} {version}: {reason}. Funcionara a partir de la version {fixed}, que aun no ha salido ({issue}). Mientras tanto puedes compilarlo con Meshtastic Oficial.",

    "step2.title": "Nodo",
    "step2.longName": "Nombre largo",
    "step2.longNamePlaceholder": "Obligatorio, p. ej. Nodo Azotea Centro",
    "step2.shortName": "Nombre corto",
    "step2.shortNamePlaceholder": "Obligatorio, 4 bytes",

    "behaviour.title": "Dispositivo",
    "behaviour.hint": "Valores de fabrica aplicados en el primer arranque o tras un reset de fabrica.",
    "behaviour.rebroadcast": "Modo de retransmision",
    "behaviour.nodeInfoSecs": "Intervalo de node info (s)",
    "behaviour.nodeInfoHint": "Minimo 3600. Por defecto 259200 (72 h).",
    "behaviour.telemHint": "Vacio = telemetria desactivada.",
    "behaviour.deviceTelem": "Telemetria de dispositivo (s)",

    "step3.title": "Radio LoRa",
    "step3.region": "Region LoRa",
    "step3.role": "Rol del dispositivo",
    "step3.preset": "Preset de modem",
    "step3.presetDisabled": "Desactivado: estas usando configuracion LoRa manual.",
    "step3.txPower": "Potencia TX (dBm)",
    "step3.txPowerHint": "Vacio o 0 = maximo legal de la region.",
    "step3.mqttHead": "Puente MQTT",
    "step3.ignoreMqtt": "Ignorar paquetes que llegan por MQTT",
    "step3.ignoreMqttHint": "El nodo no reenvia a la malla lo que recibe del broker.",
    "step3.okToMqttHint": "Permite subir a MQTT los paquetes de este nodo.",

    "radios.title": "Bluetooth y WiFi",
    "radios.hint": "PIN de emparejamiento y red WiFi del nodo.",
    "radios.bluetoothHead": "Bluetooth",
    "radios.blePinHint": "Opcional. Vacio, no se fija ningun PIN y el firmware usa el suyo (aleatorio si el nodo tiene pantalla).",
    "radios.blePin": "PIN fijo (6 digitos)",
    "radios.blePinPlaceholder": "p. ej. 121212",
    "radios.wifiHead": "WiFi",
    "radios.wifiUnsupported": "El dispositivo seleccionado no tiene WiFi.",
    "radios.wifiEnabled": "Activar WiFi",
    "radios.wifiHint": "Solo en placas ESP32. Aumenta bastante el consumo.",
    "radios.wifiSsid": "Nombre de red (SSID)",
    "radios.wifiPsk": "Contraseña WiFi",
    "radios.wifiPskHint": "Se compila en el firmware en claro, igual que la de MQTT.",

    "extra.title": "Otros valores de configuracion",
    "extra.hint": "Cualquier clave de userPrefs.jsonc que no tenga control propio.",
    "extra.help": "Se validan igual que el resto: si el valor no encaja con la clave, la peticion se rechaza.",
    "extra.add": "+ Valor",
    "extra.key": "Clave",
    "extra.value": "Valor",
    "extra.choose": "Elige una clave",

    "position.title": "Posicion y GPS",
    "position.hint": "Modo de GPS, intervalos y posicion fija.",
    "position.gpsMode": "Modo de GPS",
    "position.gpsInterval": "Intervalo de GPS (s)",
    "position.broadcastInterval": "Intervalo de emision de posicion (s)",
    "position.broadcastHint": "Por defecto 259200 (72 h).",
    "position.smart": "Emision inteligente de posicion",
    "position.smartHint": "Emite al moverse en vez de a intervalo fijo.",
    "position.blockOnEvent": "Bloquear posicion en el canal de eventos",
    "position.blockOnEventHint": "No emite ni acepta posicion en canales con la clave del canal 0.",
    "position.fixedHead": "Posicion fija",
    "position.fixedEnabled": "Usar una posicion fija",
    "position.fixedHint": "Solo se aplica en el primer arranque o tras un reset de fabrica.",
    "position.lat": "Latitud",
    "position.lon": "Longitud",
    "position.alt": "Altitud (m)",

    "security.title": "Seguridad",
    "security.hint": "Claves de administracion remota y firma de paquetes.",

    "step4.title": "Canales",
    "step4.hint": "Hasta {max} canales escritos en el firmware.",
    "step4.add": "+ Canal",
    "channel.name": "Nombre",
    "channel.psk": "Clave (base64)",
    "channel.precision": "Precision",
    "channel.downlink": "Downlink",
    "channel.uplink": "Uplink",
    "channel.muted": "Silenciado",
    "channel.remove": "Quitar",
    "channel.reorder": "Arrastra para reordenar",
    "channel.precisionOff": "Sin posicion",
    "channel.precisionExact": "Exacta",
    "channel.defaultName": "Canal",

    "step5.tz": "Zona horaria (TZ POSIX)",
    "step5.tzPeninsula": "Peninsula y Baleares",
    "step5.tzCanarias": "Canarias",
    "step5.mqttHead": "MQTT",
    "mqtt.hint": "Servidor, credenciales y reenvio de paquetes.",
    "step5.mqttAddress": "Servidor MQTT",
    "step5.mqttEnabled": "Activar MQTT",
    "step5.mqttUsername": "Usuario MQTT",
    "step5.mqttPassword": "Contraseña MQTT",
    "step5.mqttPasswordHint": "Se compila en el firmware en claro. Usa credenciales dedicadas.",
    "step5.mqttRoot": "Topic raiz",
    "step5.mqttEncryption": "Cifrado de paquetes MQTT",
    "step5.mqttTls": "TLS",
    "step5.securityHead": "Seguridad",
    "step5.adminKey": "Clave de administracion remota (base64)",
    "step5.adminKey1": "Clave de administracion 2 (base64)",
    "step5.adminKey2": "Clave de administracion 3 (base64)",
    "step5.signaturePolicy": "Politica de firma de paquetes",
    "step5.isManaged": "Modo gestionado (bloquea la configuracion)",
    "step5.isManagedHint": "Requiere al menos una clave de administracion.",

    "step6.badge": "Parche de codigo",
    "step6.warning":
      "Estas opciones modifican el codigo fuente del firmware antes de compilar. No forman parte de userPrefs.jsonc y solo estan disponibles en versiones recientes. Usalas bajo tu responsabilidad.",
    "step6.unavailable": "No disponible para la version de firmware seleccionada.",
    "step6.okToMqtt": "Permitir reenvio a MQTT por defecto (ok_to_mqtt)",
    "step6.customLora": "Configuracion LoRa manual (desactiva el preset)",
    "step6.customLoraHint":
      "Comprueba que los parametros sean legales en tu region antes de emitir.",
    "step6.bandwidth": "Ancho de banda (kHz)",
    "step6.spreadFactor": "Spreading factor",
    "step6.codingRate": "Coding rate",
    "step6.channelNum": "Slot de frecuencia",
    "step6.channelNumHint": "0 = automatico segun la region",
    "step6.overrideFreq": "Frecuencia manual (MHz)",
    "step6.overrideFreqHint": "0 = usar la frecuencia de la region. Comprueba que sea legal donde estas.",

    "step7.title": "Revisar y solicitar",
    "step7.preview": "Ver userPrefs.jsonc generado",
    "preview.injected": "Opciones avanzadas, el servidor las inyecta al compilar:",
    "preview.defaults": "Valores por defecto de esta version de firmware",
    "step7.noEmail": "No se envia ningun email. Al enviar obtendras un enlace privado: guardalo.",
    "step7.submit": "Solicitar compilacion",
    "step7.ttl": "El ZIP se borra {days} dias despues de compilarse.",

    "import.open": "Importar userPrefs",
    "import.title": "Importar userPrefs",
    "import.help":
      "Pega el userPrefs.jsonc que te mostro esta pagina (o elige el fichero) y se rellena el formulario. El firmware, la version y el dispositivo no van en el JSON: se mantienen los que tengas elegidos. El nombre largo y el corto tampoco se importan: cada nodo necesita el suyo.",
    "import.placeholder": "{\n  \"USERPREFS_CONFIG_LORA_REGION\": \"meshtastic_Config_LoRaConfig_RegionCode_EU_868\",\n  ...\n}",
    "import.pickFile": "Elegir fichero...",
    "import.cancel": "Cancelar",
    "import.confirm": "Importar",
    "import.done": "Valores importados: {n}. El nombre del nodo no se importa: escribelo.",
    "import.ignored": "Esta version de firmware no tiene: {keys}.",
    "import.mismatch": "Revisa estos, no se pudieron poner igual: {keys}.",
    "import.errEmpty": "Pega un JSON o elige un fichero.",
    "import.errTooBig": "El fichero pasa de {kb} KB.",
    "import.errSyntax": "El JSON no es valido: {detail}",
    "import.errNotObject": "El JSON debe ser un objeto { ... } con claves USERPREFS_.",
    "import.errKeys": "Estas claves no son de userPrefs: {keys}",
    "import.errValue": "El valor de {key} debe ser texto, numero o true/false.",
    "import.errNoPrefs": "El JSON no tiene ninguna clave USERPREFS_.",
    "import.errBytes": "{key} no es una lista de bytes valida ({bytes} bytes, p. ej. { 0x01, 0x02 }).",
    "import.errFile": "No se pudo leer el fichero.",
    "import.errNotReady": "Espera a que cargue la version de firmware y vuelve a probar.",
    "import.errForm": "No se pudo aplicar: {detail}",

    "result.title": "Peticion creada",
    "result.keep": "Guarda este enlace: es la unica forma de volver a tu compilacion.",
    "result.titleView": "Tu compilacion",
    "result.keepView": "Guarda esta pagina: es la unica forma de volver a tu compilacion.",
    "result.copy": "Copiar",
    "result.copied": "Enlace copiado.",
    "result.status": "Estado",
    "result.node": "Nodo",
    "result.shortName": "Nombre corto",
    "result.device": "Dispositivo",
    "result.firmware": "Firmware",
    "result.download": "Descarga",
    "result.ttl": "El ZIP estara disponible durante {days} dias desde que termine la compilacion.",
    "result.ttlUntil": "Descarga disponible hasta el {date}.",
    "result.pending": "Disponible al finalizar",
    "result.downloadZip": "Descargar ZIP",
    "result.failed": "La compilacion fallo",
    "result.expired": "El ZIP ha caducado.",

    "status.loadingTags": "Cargando tags...",
    "status.refreshingTags": "Actualizando tags...",
    "status.ready": "Listo.",
    "status.creating": "Creando peticion...",
    "status.queued": "Peticion en cola.",
    "status.loadingBuild": "Cargando compilacion...",

    "buildStatus.queued": "En cola",
    "buildStatus.running": "Compilando",
    "buildStatus.succeeded": "Completada",
    "buildStatus.failed": "Fallida",
    "buildStatus.expired": "Caducada",

    "queue.ahead": "{n} por delante",
    "queue.aheadOne": "1 por delante",
    "queue.readyIn": "lista en {time}",
    "queue.remaining": "quedan {time}",
    "queue.overrun": "tardando mas de lo habitual",
    "queue.underMinute": "<1 min",

    "error.noVersions": "No hay versiones soportadas en cache.",
    "error.template": "No se pudo cargar userPrefs.jsonc.",
    "error.longName": "El nombre largo no puede superar {bytes} bytes en esta version de firmware: el nodo lo cortaria.",
    "error.shortName": "El nombre corto no puede superar 4 bytes.",
    "error.ownerNames": "Escribe el nombre largo y el nombre corto del nodo.",
    "error.blePin": "El PIN de Bluetooth debe tener 6 cifras y no empezar por 0.",
    "error.channelName": "El canal {n} necesita nombre.",
    "error.channelPrecision": "La precision del canal {n} debe estar entre 0 y 32.",
    "error.base64": "{label} debe estar en base64 valido.",
    "error.base64Length": "{label} debe estar en base64 valido de {bytes} bytes.",
    "error.maxBytes": "{label} no puede superar {bytes} bytes.",
    "error.mustBeText": "{label} no puede ser solo digitos ni parecer un numero: el firmware lo compilaria sin comillas.",
    "label.channelKey": "La clave del canal {n}",
    "label.adminKey": "La clave de administracion remota",
    "label.adminKey1": "La clave de administracion 2",
    "label.adminKey2": "La clave de administracion 3",
    "label.mqttAddress": "El servidor MQTT",
    "label.mqttUsername": "El usuario MQTT",
    "label.mqttPassword": "La contraseña MQTT",
    "label.mqttRoot": "El topic raiz MQTT",
    "label.wifiSsid": "El SSID WiFi",
    "label.wifiPsk": "La contraseña WiFi",

    "nav.about": "Acerca de",

    "buildError.title": "Por que fallo",
    "buildError.detail": "Detalle tecnico",
    "buildError.followUp":
      "Vamos a estudiar este error para intentar solucionarlo. Si tienes cualquier duda, escribe a <a href=\"https://t.me/lazynoda\" target=\"_blank\" rel=\"noreferrer\">@lazynoda</a> en Telegram.",
    "buildError.patch_failed":
      "No se pudo aplicar al codigo del firmware una modificacion que esta compilacion necesitaba.",
    "buildError.patch_failedHint":
      "Esa modificacion no encaja en la version que elegiste. Prueba otra version de firmware, o desactiva las opciones avanzadas.",
    "buildError.compile_error": "El firmware no compilo con esta combinacion de version, dispositivo y ajustes.",
    "buildError.compile_errorHint":
      "Casi siempre es un fallo del propio firmware en esa version, no de lo que pusiste. Prueba con otra version.",
    "buildError.firmware_too_big": "El firmware compilado no cabe en la memoria de este dispositivo.",
    // No hint: what fits in flash is the firmware's doing, not something the user can change.
    "buildError.firmware_too_bigHint": "",
    "buildError.no_artifacts": "La compilacion termino sin generar ningun fichero de firmware.",
    "buildError.no_artifactsHint": "Vuelve a intentarlo. Si se repite con el mismo dispositivo, avisame.",
    "buildError.timeout": "La compilacion tardo demasiado y se cancelo.",
    "buildError.timeoutHint": "Vuelve a intentarlo: suele salir a la segunda, con las dependencias ya en cache.",
    "buildError.infrastructure": "Fallo el sistema de compilacion, no tu configuracion.",
    "buildError.infrastructureHint": "No es culpa tuya. Vuelve a intentarlo en un rato.",
    "buildError.internal": "Fallo el sistema de compilacion, no tu configuracion.",
    "buildError.internalHint": "No es culpa tuya. Vuelve a intentarlo en un rato.",
    "buildError.unknown": "La compilacion fallo por un motivo que no supimos identificar.",
    "buildError.unknownHint": "Vuelve a intentarlo. Si se repite, avisame con el enlace de esta pagina.",
    "about.title": "Sobre este proyecto",
    "nav.builder": "Volver al compilador",
    "about.whatTitle": "Que es esto",
    "about.what":
      "Firmware Meshtastic compilado con tus preferencias ya dentro, en lugar del firmware de serie que llega con la region, los nombres, la seguridad y casi todo lo demas sin configurar. Rellenas el formulario, el servidor compila el firmware para tu dispositivo y te descargas el ZIP.",
    "about.whereTitle": "Donde se ejecuta",
    "about.where":
      "La pagina y el compilador corren en un VPS de Oracle en Madrid gestionado por <a href=\"https://t.me/lazynoda\" target=\"_blank\" rel=\"noreferrer\">@lazynoda</a> (o sea, yo). Si, tecnicamente podria ver tu contraseña WiFi. No lo voy a hacer. Tampoco me voy a plantar en tu casa, a cientos de kilometros, solo para usar tu WiFi.",
    "about.retentionTitle": "Cuanto se guarda tu build",
    "about.retention":
      "Tu build y su ZIP se guardan {days} dias desde que termina la compilacion, para que tengas tiempo de descargarlo. Despues, un script automatico los borra.",
    "about.firmwareTitle": "Que firmware se usa",
    "about.firmware":
      "El firmware es el original de <a href=\"https://github.com/meshtastic/firmware\" target=\"_blank\" rel=\"noreferrer\">github.com/meshtastic/firmware</a>. Casi todas las compilaciones salen sin tocar una sola linea. Hay exactamente dos casos en los que se modifica el codigo antes de compilar, y son estos:",
    "about.mod1Title": "Configuracion LoRa manual por debajo de la 2.8",
    "about.mod1":
      "Esas versiones convierten en define cada clave de <code>userPrefs.jsonc</code>, pero luego no leen las de LoRa manual ni la de <code>okToMqtt</code>, asi que lo que pides se compila y se ignora. El parche añade los <code>#ifdef</code> que faltan en <code>installDefaultConfig()</code> para que se lean de verdad. Desde la 2.8 el firmware ya los lee solo y no se parchea nada. El formulario marca estas opciones como <em>Parche de codigo</em> cuando las activas.",
    "about.mod2Title": "Posicion fija en la 2.8.0",
    "about.mod2":
      "La 2.8 reorganizo NodeDB y dejo el bloque de posicion fija usando una variable que ya no existe, asi que cualquier compilacion con posicion fija se cae con <code>'info' was not declared in this scope</code>. Upstream no lo detecta porque su <code>userPrefs.jsonc</code> lleva esas claves comentadas y ese bloque nunca se compila alli. Aqui se aplica el arreglo de los propios desarrolladores de Meshtastic, <a href=\"https://github.com/meshtastic/firmware/pull/11825\" target=\"_blank\" rel=\"noreferrer\">PR #11825</a>, copiado tal cual y sin cambiarle nada. Desde la 2.8.1 el arreglo ya viene en el firmware y no se aplica nada. Por debajo de la 2.8 tampoco hace falta: ahi la posicion fija compila tal cual, y no se toca nada.",
    "about.firmwareClosing":
      "Los dos parches estan en <a href=\"https://github.com/lazynoda/meshtastic-builder/tree/main/docker/patches\" target=\"_blank\" rel=\"noreferrer\">el repositorio de este servicio</a>, se pueden leer enteros, y nunca los escribe quien pide la compilacion. Si un parche no aplica limpiamente, la compilacion se para antes de compilar en vez de seguir sin el.",
    "about.comingSoon":
      "En breves vendra un cambio mas: poder fijar la clave privada del nodo. Desde la 2.8 el ID del nodo se calcula a partir de esa clave, asi que un reset de fabrica mantiene el mismo ID si la clave esta fijada. Publicare los cambios exactos cuando este hecho.",
    "about.trustTitle": "Confianza",
    "about.trust":
      "Se que lo siguiente va contra esta misma pagina, pero por razones obvias hay que decirlo: no aceptes firmware de fuentes en las que no confies. Puede llevar no solo preferencias de usuario distintas, sino un comportamiento alterado del firmware, que incluso podria incumplir la normativa de tu pais. Solo fuentes de confianza.",
    "about.diy":
      "Si prefieres compilarlo tu mismo, copia el <code>userPrefs.jsonc</code> generado y sigue la <a href=\"https://meshtastic.es/docs/configuracion-avanzada/preferencias-de-usuario\" target=\"_blank\" rel=\"noreferrer\">guia de preferencias de usuario de meshtastic.es</a>.",
  },
  en: {
    "page.title": "Meshtastic Builder",
    "header.tagline": "Custom Meshtastic firmware without hand-editing JSON",
    "footer.trademark":
      "Meshtastic is a registered trademark of Meshtastic LLC. This project is not affiliated with or endorsed by Meshtastic LLC, nor by any of the device brands listed. It is a hobby project.",
    "footer.source":
      "<a href=\"https://github.com/lazynoda/meshtastic-builder\" target=\"_blank\" rel=\"noreferrer\">Source code</a> under the AGPL-3.0 license.",

    "step1.title": "Firmware and device",
    "step1.device": "Device",
    "step1.mui": "Meshtastic UI",
    "help.label": "Help",
    "step1.muiHint": "Builds the Meshtastic UI (MUI) variant, the touch interface for the board's screen. Same as the Web Flasher's switch.",
    "step1.devicePlaceholder": "Search for a device",
    "step1.firmware": "Firmware",
    "step1.version": "Firmware version",
    "step1.noVersion": "N/A",
    "step1.branchHint": "No releases: builds the {branch} branch ({version}, {sha}).",
    "device.unavailable": "unavailable",
    "device.unavailableHint": "Not available with {firmware} for now: {reason}. We are working on it ({issue}). Meanwhile you can build it with Meshtastic Oficial.",
    "device.unavailable.firmware_too_big": "the firmware does not fit in this board's flash memory",
    "device.unavailableFixedHint": "Not available with {firmware} {version}: {reason}. It works from {firmware} {tag}.",
    "device.unavailableComingHint":
      "Not available with {firmware} {version}: {reason}. It will work from version {fixed}, which is not out yet ({issue}). Meanwhile you can build it with Meshtastic Oficial.",

    "step2.title": "Node",
    "step2.longName": "Long name",
    "step2.longNamePlaceholder": "Required, e.g. Downtown Rooftop Node",
    "step2.shortName": "Short name",
    "step2.shortNamePlaceholder": "Required, 4 bytes",

    "behaviour.title": "Device",
    "behaviour.hint": "Factory defaults applied on first boot or after a factory reset.",
    "behaviour.rebroadcast": "Rebroadcast mode",
    "behaviour.nodeInfoSecs": "Node info interval (s)",
    "behaviour.nodeInfoHint": "Minimum 3600. Defaults to 259200 (72 h).",
    "behaviour.telemHint": "Empty = telemetry disabled.",
    "behaviour.deviceTelem": "Device telemetry (s)",

    "step3.title": "LoRa radio",
    "step3.region": "LoRa region",
    "step3.role": "Device role",
    "step3.preset": "Modem preset",
    "step3.presetDisabled": "Disabled: you are using a manual LoRa configuration.",
    "step3.txPower": "TX power (dBm)",
    "step3.txPowerHint": "Empty or 0 = region legal maximum.",
    "step3.mqttHead": "MQTT bridge",
    "step3.ignoreMqtt": "Ignore packets arriving over MQTT",
    "step3.ignoreMqttHint": "The node does not repeat onto the mesh what it receives from the broker.",
    "step3.okToMqttHint": "Lets this node's packets be uploaded to MQTT.",

    "radios.title": "Bluetooth and WiFi",
    "radios.hint": "Pairing PIN and the node's WiFi network.",
    "radios.bluetoothHead": "Bluetooth",
    "radios.blePinHint": "Optional. Left empty, no PIN is baked in and the firmware uses its own (random if the node has a screen).",
    "radios.blePin": "Fixed PIN (6 digits)",
    "radios.blePinPlaceholder": "e.g. 121212",
    "radios.wifiHead": "WiFi",
    "radios.wifiUnsupported": "The selected device has no WiFi.",
    "radios.wifiEnabled": "Enable WiFi",
    "radios.wifiHint": "ESP32 boards only. Raises power draw noticeably.",
    "radios.wifiSsid": "Network name (SSID)",
    "radios.wifiPsk": "WiFi password",
    "radios.wifiPskHint": "Compiled into the firmware in clear text, like the MQTT one.",

    "extra.title": "Other config values",
    "extra.hint": "Any userPrefs.jsonc key without a control of its own.",
    "extra.help": "Validated like the rest: a value that does not match its key is rejected.",
    "extra.add": "+ Value",
    "extra.key": "Key",
    "extra.value": "Value",
    "extra.choose": "Pick a key",

    "position.title": "Position and GPS",
    "position.hint": "GPS mode, intervals and fixed position.",
    "position.gpsMode": "GPS mode",
    "position.gpsInterval": "GPS interval (s)",
    "position.broadcastInterval": "Position broadcast interval (s)",
    "position.broadcastHint": "Defaults to 259200 (72 h).",
    "position.smart": "Smart position broadcast",
    "position.smartHint": "Broadcasts on movement instead of on a fixed interval.",
    "position.blockOnEvent": "Block position on the event channel",
    "position.blockOnEventHint": "Neither sends nor accepts position on channels keyed like channel 0.",
    "position.fixedHead": "Fixed position",
    "position.fixedEnabled": "Use a fixed position",
    "position.fixedHint": "Applied only on first boot or after a factory reset.",
    "position.lat": "Latitude",
    "position.lon": "Longitude",
    "position.alt": "Altitude (m)",

    "security.title": "Security",
    "security.hint": "Remote admin keys and packet signing.",

    "step4.title": "Channels",
    "step4.hint": "Up to {max} channels written into the firmware.",
    "step4.add": "+ Channel",
    "channel.name": "Name",
    "channel.psk": "Key (base64)",
    "channel.precision": "Precision",
    "channel.downlink": "Downlink",
    "channel.uplink": "Uplink",
    "channel.muted": "Muted",
    "channel.remove": "Remove",
    "channel.reorder": "Drag to reorder",
    "channel.precisionOff": "No position",
    "channel.precisionExact": "Exact",
    "channel.defaultName": "Channel",

    "step5.tz": "Time zone (POSIX TZ)",
    "step5.tzPeninsula": "Peninsula and Balearic Islands",
    "step5.tzCanarias": "Canary Islands",
    "step5.mqttHead": "MQTT",
    "mqtt.hint": "Broker, credentials and packet forwarding.",
    "step5.mqttAddress": "MQTT server",
    "step5.mqttEnabled": "Enable MQTT",
    "step5.mqttUsername": "MQTT username",
    "step5.mqttPassword": "MQTT password",
    "step5.mqttPasswordHint": "Compiled into the firmware in clear text. Use dedicated credentials.",
    "step5.mqttRoot": "Root topic",
    "step5.mqttEncryption": "MQTT packet encryption",
    "step5.mqttTls": "TLS",
    "step5.securityHead": "Security",
    "step5.adminKey": "Remote admin key (base64)",
    "step5.adminKey1": "Admin key 2 (base64)",
    "step5.adminKey2": "Admin key 3 (base64)",
    "step5.signaturePolicy": "Packet signature policy",
    "step5.isManaged": "Managed mode (locks the configuration)",
    "step5.isManagedHint": "Requires at least one admin key.",

    "step6.badge": "Source patch",
    "step6.warning":
      "These options patch the firmware source before compiling. They are not part of userPrefs.jsonc and are only available on recent versions. Use at your own risk.",
    "step6.unavailable": "Not available for the selected firmware version.",
    "step6.okToMqtt": "Allow MQTT forwarding by default (ok_to_mqtt)",
    "step6.customLora": "Manual LoRa configuration (disables the preset)",
    "step6.customLoraHint": "Check that these parameters are legal in your region before transmitting.",
    "step6.bandwidth": "Bandwidth (kHz)",
    "step6.spreadFactor": "Spreading factor",
    "step6.codingRate": "Coding rate",
    "step6.channelNum": "Frequency slot",
    "step6.channelNumHint": "0 = automatic for the region",
    "step6.overrideFreq": "Manual frequency (MHz)",
    "step6.overrideFreqHint": "0 = use the region frequency. Check that it is legal where you are.",

    "step7.title": "Review and submit",
    "step7.preview": "Show generated userPrefs.jsonc",
    "preview.injected": "Advanced options, injected by the server at build time:",
    "preview.defaults": "Defaults from this firmware version",
    "step7.noEmail": "No email is sent. Submitting gives you a private link: keep it.",
    "step7.submit": "Request build",
    "step7.ttl": "The ZIP is deleted {days} days after it is built.",

    "import.open": "Import userPrefs",
    "import.title": "Import userPrefs",
    "import.help":
      "Paste the userPrefs.jsonc this page showed you (or pick the file) and the form is filled in. Firmware, version and device are not in the JSON: whatever you have selected stays. The long and short names are not imported either: every node needs its own.",
    "import.placeholder": "{\n  \"USERPREFS_CONFIG_LORA_REGION\": \"meshtastic_Config_LoRaConfig_RegionCode_EU_868\",\n  ...\n}",
    "import.pickFile": "Choose file...",
    "import.cancel": "Cancel",
    "import.confirm": "Import",
    "import.done": "Values imported: {n}. The node name is never imported: type it in.",
    "import.ignored": "This firmware version has no: {keys}.",
    "import.mismatch": "Check these, they could not be set the same: {keys}.",
    "import.errEmpty": "Paste a JSON or choose a file.",
    "import.errTooBig": "The file is over {kb} KB.",
    "import.errSyntax": "The JSON is not valid: {detail}",
    "import.errNotObject": "The JSON must be an object { ... } with USERPREFS_ keys.",
    "import.errKeys": "These keys are not userPrefs: {keys}",
    "import.errValue": "The value of {key} must be text, a number or true/false.",
    "import.errNoPrefs": "The JSON has no USERPREFS_ keys.",
    "import.errBytes": "{key} is not a valid byte list ({bytes} bytes, e.g. { 0x01, 0x02 }).",
    "import.errFile": "Could not read the file.",
    "import.errNotReady": "Wait for the firmware version to load and try again.",
    "import.errForm": "Could not apply it: {detail}",

    "result.title": "Request created",
    "result.keep": "Save this link: it is the only way back to your build.",
    "result.titleView": "Your build",
    "result.keepView": "Bookmark this page: it is the only way back to your build.",
    "result.copy": "Copy",
    "result.copied": "Link copied.",
    "result.status": "Status",
    "result.node": "Node",
    "result.shortName": "Short name",
    "result.device": "Device",
    "result.firmware": "Firmware",
    "result.download": "Download",
    "result.ttl": "The ZIP stays available for {days} days after the build finishes.",
    "result.ttlUntil": "Download available until {date}.",
    "result.pending": "Available when finished",
    "result.downloadZip": "Download ZIP",
    "result.failed": "The build failed",
    "result.expired": "The ZIP has expired.",

    "status.loadingTags": "Loading tags...",
    "status.refreshingTags": "Refreshing tags...",
    "status.ready": "Ready.",
    "status.creating": "Creating request...",
    "status.queued": "Request queued.",
    "status.loadingBuild": "Loading build...",

    "buildStatus.queued": "Queued",
    "buildStatus.running": "Building",
    "buildStatus.succeeded": "Completed",
    "buildStatus.failed": "Failed",
    "buildStatus.expired": "Expired",

    "queue.ahead": "{n} ahead",
    "queue.aheadOne": "1 ahead",
    "queue.readyIn": "ready in {time}",
    "queue.remaining": "{time} left",
    "queue.overrun": "taking longer than usual",
    "queue.underMinute": "<1 min",

    "error.noVersions": "No supported versions in cache.",
    "error.template": "Could not load userPrefs.jsonc.",
    "error.longName": "The long name cannot exceed {bytes} bytes on this firmware version: the node would cut it.",
    "error.shortName": "The short name cannot exceed 4 bytes.",
    "error.ownerNames": "Enter the node's long name and short name.",
    "error.blePin": "The Bluetooth PIN must have 6 digits and not start with 0.",
    "error.channelName": "Channel {n} needs a name.",
    "error.channelPrecision": "Channel {n} precision must be between 0 and 32.",
    "error.base64": "{label} must be valid base64.",
    "error.base64Length": "{label} must be valid base64 of {bytes} bytes.",
    "error.maxBytes": "{label} cannot exceed {bytes} bytes.",
    "error.mustBeText": "{label} cannot be only digits or look like a number: the firmware would compile it unquoted.",
    "label.channelKey": "The channel {n} key",
    "label.adminKey": "The remote admin key",
    "label.adminKey1": "Admin key 2",
    "label.adminKey2": "Admin key 3",
    "label.mqttAddress": "The MQTT server",
    "label.mqttUsername": "The MQTT username",
    "label.mqttPassword": "The MQTT password",
    "label.mqttRoot": "The MQTT root topic",
    "label.wifiSsid": "The WiFi SSID",
    "label.wifiPsk": "The WiFi password",

    "nav.about": "About",

    "buildError.title": "Why it failed",
    "buildError.detail": "Technical detail",
    "buildError.followUp":
      "We will look into this error and try to fix it. If you have any questions, message <a href=\"https://t.me/lazynoda\" target=\"_blank\" rel=\"noreferrer\">@lazynoda</a> on Telegram.",
    "buildError.patch_failed":
      "A change this build needed could not be applied to the firmware source.",
    "buildError.patch_failedHint":
      "That change does not fit the version you picked. Try another firmware version, or turn the advanced options off.",
    "buildError.compile_error": "The firmware did not compile with this combination of version, device and settings.",
    "buildError.compile_errorHint":
      "This is almost always a bug in that firmware version rather than in what you entered. Try another version.",
    "buildError.firmware_too_big": "The compiled firmware does not fit in this device's memory.",
    "buildError.firmware_too_bigHint": "",
    "buildError.no_artifacts": "The build finished without producing any firmware file.",
    "buildError.no_artifactsHint": "Try again. If it keeps happening on the same device, tell me.",
    "buildError.timeout": "The build took too long and was cancelled.",
    "buildError.timeoutHint": "Try again: it usually passes on the second run, with the dependencies already cached.",
    "buildError.infrastructure": "The build system failed, not your configuration.",
    "buildError.infrastructureHint": "Not your fault. Try again in a while.",
    "buildError.internal": "The build system failed, not your configuration.",
    "buildError.internalHint": "Not your fault. Try again in a while.",
    "buildError.unknown": "The build failed for a reason we could not identify.",
    "buildError.unknownHint": "Try again. If it keeps happening, send me the link to this page.",
    "about.title": "About this project",
    "nav.builder": "Back to the builder",
    "about.whatTitle": "What this is",
    "about.what":
      "Meshtastic firmware compiled with your preferences already baked in, instead of the stock firmware that ships with the region, the names, the security keys and most everything else unset. You fill in the form, the server compiles the firmware for your device, and you download the ZIP.",
    "about.whereTitle": "Where it runs",
    "about.where":
      "The page and the builder run on an Oracle VPS in Madrid managed by <a href=\"https://t.me/lazynoda\" target=\"_blank\" rel=\"noreferrer\">@lazynoda</a> (that is me). Yes, technically I could read your WiFi password. I am not going to. I am also not driving hundreds of kilometres to your house just to use your WiFi.",
    "about.retentionTitle": "How long your build is kept",
    "about.retention":
      "Your build and its ZIP are kept for {days} days after the build finishes, so you have time to download it. After that an automated script deletes them.",
    "about.firmwareTitle": "Which firmware is used",
    "about.firmware":
      "The firmware is the original from <a href=\"https://github.com/meshtastic/firmware\" target=\"_blank\" rel=\"noreferrer\">github.com/meshtastic/firmware</a>. Almost every build compiles without a single line touched. There are exactly two cases where the code is modified before compiling, and these are them:",
    "about.mod1Title": "Manual LoRa config below 2.8",
    "about.mod1":
      "Those versions turn every <code>userPrefs.jsonc</code> key into a compiler define, but then never read the manual LoRa ones or <code>okToMqtt</code>, so what you asked for is compiled in and ignored. The patch adds the missing <code>#ifdef</code> blocks to <code>installDefaultConfig()</code> so they are actually read. From 2.8 the firmware reads them by itself and nothing is patched. The form tags these options as <em>Source patch</em> when you enable them.",
    "about.mod2Title": "Fixed position on 2.8.0",
    "about.mod2":
      "2.8 restructured NodeDB and left the fixed-position block using a variable that no longer exists, so any build with a fixed position dies with <code>'info' was not declared in this scope</code>. Upstream never notices because their own <code>userPrefs.jsonc</code> keeps those keys commented out, so that block is never compiled there. This service applies the Meshtastic developers' own fix, <a href=\"https://github.com/meshtastic/firmware/pull/11825\" target=\"_blank\" rel=\"noreferrer\">PR #11825</a>, copied verbatim with nothing changed. From 2.8.1 the fix ships with the firmware and nothing is applied. Below 2.8 nothing is needed either: fixed position compiles as shipped and nothing is touched.",
    "about.firmwareClosing":
      "Both patches live in <a href=\"https://github.com/lazynoda/meshtastic-builder/tree/main/docker/patches\" target=\"_blank\" rel=\"noreferrer\">this service's repository</a>, can be read in full, and are never written by whoever requests a build. If a patch does not apply cleanly the build stops before compiling instead of carrying on without it.",
    "about.comingSoon":
      "One more change is coming: setting the node private key. Since 2.8 the node ID is derived from that key, so a factory reset keeps the same node ID when the key is set. I will publish the exact changes once it is done.",
    "about.trustTitle": "Trust",
    "about.trust":
      "I know the next sentence goes against this very page, but for obvious reasons it has to be said: do not accept firmware from sources you do not trust. It can carry not only different user preferences but altered firmware behaviour, which could even break the regulations where you live. Trusted sources only.",
    "about.diy":
      "If you would rather build it yourself, copy the generated <code>userPrefs.jsonc</code> and follow the <a href=\"https://meshtastic.es/docs/configuracion-avanzada/preferencias-de-usuario\" target=\"_blank\" rel=\"noreferrer\">user preferences guide on meshtastic.es</a>.",
  },
};

let lang = localStorage.getItem("mb-lang");
if (!DICT[lang]) {
  lang = (navigator.language || "es").toLowerCase().startsWith("es") ? "es" : "en";
}

function t(key, vars) {
  let text = DICT[lang][key] ?? DICT.es[key] ?? key;
  if (vars) {
    for (const [name, value] of Object.entries(vars)) {
      text = text.replaceAll(`{${name}}`, value);
    }
  }
  return text;
}

function currentLang() {
  return lang;
}

function applyI18n() {
  document.documentElement.lang = lang;
  document.title = t("page.title");
  for (const el of document.querySelectorAll("[data-i18n]")) {
    el.textContent = t(el.dataset.i18n);
  }
  // A few strings carry inline links or <code> spans. They come from the
  // dictionary above, never from user input, so writing them as HTML is safe.
  for (const el of document.querySelectorAll("[data-i18n-html]")) {
    el.innerHTML = t(el.dataset.i18nHtml);
  }
  for (const el of document.querySelectorAll("[data-i18n-placeholder]")) {
    el.placeholder = t(el.dataset.i18nPlaceholder);
  }
  for (const el of document.querySelectorAll("[data-i18n-aria-label]")) {
    el.setAttribute("aria-label", t(el.dataset.i18nAriaLabel));
  }
  for (const button of document.querySelectorAll("[data-lang]")) {
    button.classList.toggle("is-active", button.dataset.lang === lang);
  }
}

function setLang(next) {
  if (!DICT[next] || next === lang) return;
  lang = next;
  localStorage.setItem("mb-lang", lang);
  applyI18n();
  document.dispatchEvent(new CustomEvent("languagechange"));
}
