# Room Sentinel — Research Brief: The Transfer Problem

## What we're building

A privacy-preserving system that answers one question: **"How many wireless devices are inside this room right now, and what type are they?"** (e.g., 2 phones, 1 pair of earbuds). It never identifies who owns them — just categories and counts.

The hardware is simple: 3–4 cheap ESP32 microcontrollers ($5 each) placed in the corners of a room. Each one passively listens for Bluetooth Low Energy (BLE) advertisements — the signals that phones, earbuds, smartwatches, and laptops constantly broadcast. Each satellite reports what it hears (device address, signal strength/RSSI, manufacturer data) over WiFi to a central "brain" (a laptop or Raspberry Pi) that runs a machine learning model to classify each device as **inside** or **outside** the room.

## The core insight that makes this work (in theory)

A single sensor can't reliably tell inside from outside. A phone in your pocket 2 meters away might read -70 dBm, while a neighbor's phone through a thin wall 3 meters away also reads -70 dBm. The distributions genuinely overlap.

But with **multiple sensors in different corners**, you get RSSI *differences* between sensors: RSSI_sensor1 − RSSI_sensor2. These differences **cancel out the device's transmit power** (a loud phone and a quiet earbud at the same spot produce the same difference) and encode the **geometry** — which walls are between the device and each sensor, and how the person's body shadows the signal.

An inside device has **anisotropic** signal patterns: the person's body blocks some sensors but not others, and as they turn, the loudest sensor rotates. An outside device has **correlated** drops: every path crosses the same wall, so all sensors see a similar, static attenuation. These are fundamentally different patterns, and a model can learn to tell them apart.

We proved this works: with a calibration beacon (a dedicated ESP32 that broadcasts at known positions), the 3-sensor array achieved **3.9% false positive rate on devices just past the shared wall** (down from 95% with a single sensor) while maintaining **95.7% recall on a device in someone's pocket**. The physics is validated.

## The problem: the model doesn't transfer from beacon to real devices

The calibration process works like this: you carry a beacon (an ESP32 that constantly advertises BLE) to ~12 positions in and around the room, spending ~90 seconds at each. The satellites record the beacon's RSSI at each position, and you label each position as "inside" or "outside." A Random Forest model trains on this data using Leave-One-Position-Out cross-validation.

The beacon model achieves excellent results — on the beacon. But when we turn on the live system and real phones and earbuds are in the room, they score far too low. The model gives real devices probabilities of 0.01–0.57 when it should give inside devices 0.80+.

We ran diagnostic experiments to understand why, and the answer is clear:

### It's a discrimination problem, not a calibration problem

**AUC = 0.586** when scoring real devices with the beacon model. That's barely above random (0.5). It means the model can't even rank inside devices above outside devices — it's not just that the probabilities are on the wrong scale, the model genuinely can't tell the difference for real devices.

### Why it fails — three specific causes

**1. The model learned "inside = loud" instead of "inside = specific geometric pattern"**

The top features by importance are all absolute RSSI values:
- `rssi_max__esp_c3` (12.4% importance) — "what's the loudest signal sensor 3 heard?"
- `rssi_vec_max` (9.8%) — "what's the loudest signal ANY sensor heard?"
- `rssi_max__esp_c2` (7.6%)

The beacon broadcasts at relatively high power from a fixed position. Inside positions are physically close to sensors, producing loud signals. The model took the easy shortcut: loud = inside. But real phones transmit at different power levels, are in pockets (attenuating the signal), and have different antenna patterns. A real phone inside might be quieter than the beacon was outside.

We explicitly tested whether removing absolute features and keeping only the TX-power-invariant differential features (RSSI differences between sensors, which sensor is loudest, spread) would transfer better. **It transferred worse** (AUC dropped from 0.586 to 0.424). The differential features actually *inverted* — inside real devices showed the opposite pattern from inside beacon. This means the domain shift isn't just TX power; it's the whole signal geometry.

**2. Real devices are heard by fewer sensors**

The beacon, broadcasting openly at reasonable power, was heard by all 3 sensors in 97% of time windows. Real devices (phones in pockets, earbuds in ears) are heard by all 3 sensors only 72% of the time. 28% of real-device windows have gaps where one or more sensors didn't hear the device at all.

When a sensor doesn't hear a device, its features get filled with a sentinel value (-120 dBm). This creates a completely different feature vector that the model never saw during training on the always-audible beacon.

**3. The "rotating loudest sensor" signal is domain-shifted**

One of our most theoretically promising features is `argmax_stability` — it measures whether the same sensor stays loudest across multiple time windows. The thesis: an inside person turns their body, rotating which sensor has the clearest path, making the argmax unstable. An outside device has a static path through the wall, keeping the same sensor loudest.

On beacon data this somewhat works (inside stability = 0.928, outside = 0.873). On real devices it's inverted (inside = 0.680, outside = 0.706) and has no separation. The feature is rank #34 out of 38 in importance — essentially unused.

### What we tried that didn't work

**Training on ALL devices:** Instead of beacon-only, we trained on every BLE device heard during labeled time windows. This catastrophically failed (95% wall FP). The reason: during an "inside" labeled window, the satellites also hear dozens of neighbor devices through the walls. Those neighbors get labeled "inside" even though they're outside. This poisons the labels and the model learns nothing.

**Lowering the threshold:** Dropping from 0.80 to 0.45 and adding probability smoothing (exponential moving average) made the live system show ~2 devices (phone + earbuds) — correct! But it flickers, is unstable, and the threshold is so low that it would admit false positives from neighbors in many scenarios.

## What we need to figure out

The fundamental question: **How do you train a room boundary model that transfers across different BLE devices?**

Specific sub-questions we need researched:

### 1. RSSI normalization / domain adaptation techniques for cross-device transfer

The indoor localization literature has studied "device heterogeneity" extensively. We know about:
- **SSD (Signal Strength Difference)** — our current delta features, which didn't help
- **HLF (Hyperbolic Location Fingerprinting)** — using ratios of signal strengths instead of differences
- **Rank-based normalization** — converting RSSI vectors to rank orders (which sensor is 1st, 2nd, 3rd loudest) instead of using actual dBm values
- **Histogram equalization / quantile normalization** across devices

We need: which of these approaches actually works for **classification** (inside/outside boundary) rather than coordinate regression? Our problem is simpler than full indoor positioning — we only need a binary decision — so there may be approaches that work here that don't work for meter-level accuracy.

### 2. Mixed-device training strategies

The "right" answer is probably to train on the beacon AND real devices, but only devices that were physically at the labeled position (carried by the person doing the calibration). This requires recording which device MACs were carried at each position and filtering training data to only those MACs.

But how should we combine them? Equal weighting? Should the beacon data be used for geometry and the real-device data for threshold calibration? Is there a domain adaptation approach (like fine-tuning on a small real-device set after training on a large beacon set)?

### 3. Feature engineering for transfer

Our current 38 features are dominated by per-sensor absolute stats (27 absolute vs 11 differential). The absolute features are the most important for the beacon but the most likely to fail on different devices. Should we:
- Use ONLY differential features but with better normalization?
- Add new features designed for transfer (e.g., rank of each sensor, fraction of windows where sensor X is loudest, temporal variance)?
- Use a representation learning approach where the model learns device-invariant features?

### 4. The n_heard problem

Real devices are heard by fewer sensors (72% heard by all 3 vs 97% for beacon). This creates a feature-space gap. Options:
- Train with synthetic dropout (randomly mask sensor readings during beacon training to simulate partial hearing)
- Use only features that are defined even with partial hearing
- Explicitly model the "number of sensors that hear this device" as a separate input

### 5. Alternative model architectures

We're using a Random Forest. Would:
- Gradient boosted trees (the original design doc's recommendation) help with the noisy feature space?
- A model trained with domain adversarial training (penalizing the model for being able to distinguish beacon from real-device feature distributions)?
- A simpler approach like logistic regression on rank features (less overfitting to beacon-specific patterns)?

## Constraints

- **Privacy is non-negotiable:** No MAC address or device name ever leaves the volatile processing layer. No cross-session tracking. No fingerprinting to defeat MAC randomization.
- **Hardware is fixed:** 3–4 ESP32 corners + 1 brain. No SDRs, no expensive hardware.
- **Must work with a short calibration:** Ideally 15–30 minutes of walking positions. Nobody will do a 2-hour calibration.
- **Must work across rooms:** A model that only works in one specific room layout is useless as a product.
- **BLE only for geometry:** WiFi and cellular add coverage (laptops with BT off) but can't be used for inside/outside discrimination on ESP32 hardware.

## Current data available

- **1.3M raw BLE readings** from a calibration session (3 sensors, well-balanced)
- **48,580 beacon-labeled rows** across 12 positions (6 inside, 6 outside)
- **4,890 real-device rows** across 4 positions (2 inside, 2 outside), 4 known MACs
- Beacon achieves 3.9% wall FP / 95.7% pocket recall (LOPO) — the geometry works
- Real devices achieve AUC=0.586 — the transfer fails

## The goal

Find an approach where a ~20-minute calibration walk (carrying a beacon plus 2–3 personal devices) produces a model that correctly classifies arbitrary new devices as inside/outside with ≤10% wall FP and ≥90% pocket recall, validated by LOPO on real devices.
