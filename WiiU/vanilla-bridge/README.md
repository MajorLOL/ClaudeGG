# Wii U GamePad-brug (experimenteel)

`claudegg-wiiu-bridge` laat een Raspberry Pi (of een andere Linux-machine) zich voordoen als de Wii U GamePad. ClaudeGG kan daarna via het netwerk knoppen, sticks en touch sturen en het GamePad-scherm ophalen. De console hoeft niet gemod te worden.

```
ClaudeGG (Windows) --TCP 51200: commando's--> bridge --> vanilla-pipe --5 GHz-wifi--> Wii U
ClaudeGG (Windows) <--TCP 51201: H.264-------- bridge <---------------------------------- Wii U
```

Het echte werk doet [Vanilla](https://github.com/vanilla-wiiu/vanilla) van MattKC: `vanilla-pipe` maakt de aangepaste wifi-verbinding, en de bibliotheek `libvanilla` spreekt het GamePad-protocol. Deze brug is een klein programma rond `libvanilla`. Vanilla is zelf nog alpha, en deze brug is nog niet op een echte Wii U getest.

Het TV-beeld komt niet via de brug, maar via HDMI op de gewone capturekaart.

## Wat je nodig hebt

- Raspberry Pi 4 of 5 met Raspberry Pi OS (64-bit), of een Linux-pc.
- Een USB-wifiadapter die 5 GHz 802.11n kan en op de [compatibiliteitslijst van Vanilla](https://github.com/vanilla-wiiu/vanilla/wiki/Wireless-Compatibility) als werkend staat. De ingebouwde wifi van de Pi werkt niet.
- Een netwerkverbinding tussen de Pi en de Windows-pc (kabel of de ingebouwde wifi van de Pi).
- De Wii U, dicht bij de Pi.

Let op: de Wii U koppelt maar één GamePad tegelijk. Na het koppelen van de Pi werkt de echte GamePad pas weer als je die opnieuw synchroniseert.

## Installeren op de Pi

```sh
sudo apt install build-essential cmake git libnl-genl-3-dev libnl-route-3-dev libglib2.0-dev libpolkit-agent-1-dev libxml2-dev

# 1. vanilla-pipe (de wifi-kant), zonder de grafische app
git clone https://github.com/vanilla-wiiu/vanilla.git
cmake -S vanilla -B vanilla/build -DVANILLA_BUILD_GUI=OFF
cmake --build vanilla/build --parallel
sudo cmake --install vanilla/build

# 2. deze brug
git clone https://github.com/MajorLOL/ClaudeGG.git
cmake -S ClaudeGG/WiiU/vanilla-bridge -B bridge-build
cmake --build bridge-build --parallel
```

Zoek de naam van de USB-wifiadapter op met `ip link` (meestal `wlan1`; `wlan0` is de ingebouwde wifi).

## Starten

Twee terminals op de Pi:

```sh
sudo vanilla-pipe -local wlan1
./bridge-build/claudegg-wiiu-bridge          # --region EUR is de standaard
```

Gebruik `--region USA` of `--region JPN` als de Wii U uit een andere regio komt, want de console controleert de regio van de GamePad.

## Eerste keer: koppelen

1. Druk op de Wii U op de rode SYNC-knop (of kies in het menu *GamePad synchroniseren*). De TV toont vier symbolen.
2. Stuur die symbolen naar de brug als letters: S = schoppen, H = harten, D = ruiten, C = klaveren. Vanaf een pc met Python:

   ```sh
   python bridge_client.py <ip-van-de-pi> SYNC SHDC --wait
   ```

3. Bij `EVENT SYNCED` is de console opgeslagen in `~/.config/claudegg-wiiu/console.bin` op de Pi. Dit hoeft maar één keer.

## Verbinden en testen

```sh
python bridge_client.py <ip-van-de-pi> CONNECT --wait    # wacht op EVENT CONNECTED
ffplay -f h264 tcp://<ip-van-de-pi>:51201                # GamePad-scherm live bekijken
python bridge_client.py <ip-van-de-pi> press A
python bridge_client.py <ip-van-de-pi> tap 427 240       # midden van het touchscreen
python bridge_client.py <ip-van-de-pi> record gamepad.h264 10
```

## Commando's (poort 51200)

Eén commando per regel. De brug antwoordt met `OK ...` of `ERR ...`. Gebeurtenissen die later komen, beginnen met `EVENT`.

| Commando | Betekenis |
| --- | --- |
| `PING` | Antwoordt `OK PONG` |
| `STATUS` | `OK STATE idle\|syncing\|connected CONSOLE yes\|no` |
| `SYNC SHDC` | Koppelen met de vier symbolen; later `EVENT SYNCED` of `EVENT ERROR <code>` |
| `CONNECT` | Verbinden met de opgeslagen console; bij het eerste beeld `EVENT CONNECTED` |
| `DISCONNECT` | Verbinding verbreken |
| `BTN <knop> <0\|1>` | Knop los of ingedrukt. Knoppen: A B X Y L R ZL ZR MINUS PLUS HOME TV L3 R3 UP DOWN LEFT RIGHT |
| `AXIS <LX\|LY\|RX\|RY> <waarde>` | Stick, -32768 tot 32767; negatieve Y is omhoog |
| `TOUCH <x> <y>` | Touchscreen indrukken, x 0-853 en y 0-479 |
| `TOUCH OFF` | Touchscreen loslaten |
| `RELEASE` | Alle knoppen, sticks en touch loslaten |
| `IDR` | Vraag de Wii U om een volledig beeld (keyframe) |

Foutcodes komen uit `vanilla.h` van Vanilla. Bijvoorbeeld -4 betekent dat `vanilla-pipe` niet antwoordt, en -205 dat de adapter geen 5 GHz heeft.

## Video (poort 51201)

Elke verbinding krijgt ruwe H.264 (Annex B, 854x480) van het GamePad-scherm, beginnend bij een keyframe. FFmpeg en OpenCV kunnen dit direct openen met `tcp://<ip>:51201`. Een client die niet bijhoudt, wordt afgesloten, omdat een half verstuurd beeld de stroom breekt.

## Licentie

Deze brug linkt `libvanilla`, dat onder GPL-2.0 valt. Daarom valt dit programma ook onder GPL-2.0. ClaudeGG zelf praat er alleen via sockets mee en blijft MIT.

## Later

- Een controllertype "Wii U GamePad (via Pi)" in ClaudeGG dat deze commando's stuurt, plus de video als tweede bron naast de HDMI-capture.
- Vanilla heeft ook een `vanilla-pipe` voor het goedkope RTL8720DF-bordje (`pipe/rtl8720df` in hun repo). Dat kan op termijn de wifiadapter vervangen.
