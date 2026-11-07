{
  lib,
  stdenv,
  fetchurl,
  patchelf,
  makeWrapper,
  ripgrep,
  fd,
  bash,
  cacert,
  nodejs_22,
  libxcb,
  wl-clipboard,
  xclip,
}:

let
  sources = builtins.fromJSON (builtins.readFile ./sources.json);
  platform =
    sources.platforms.${stdenv.hostPlatform.system}
      or (throw "Unsupported platform: ${stdenv.hostPlatform.system}");
  # Keep the reference package's patchelf version for Bun's ELF layout.
  bunPatchelf = patchelf.overrideAttrs (_: {
    version = "0.15.2";
    src = fetchurl {
      url = "https://github.com/NixOS/patchelf/releases/download/0.15.2/patchelf-0.15.2.tar.bz2";
      hash = "sha256-F3RfVkFZyOIo/EEtplogSLhGxLa0Igt3y/IkFuAvLXw=";
    };
    patches = [ ];
  });
in
stdenv.mkDerivation {
  pname = "pi-coding-agent";
  inherit (sources) version;

  src = fetchurl {
    url = "https://github.com/earendil-works/pi/releases/download/v${sources.version}/${platform.name}";
    inherit (platform) hash;
  };

  nativeBuildInputs = [ makeWrapper ];
  dontBuild = true;
  dontStrip = true;
  dontPatchELF = true;

  installPhase = ''
    runHook preInstall
    mkdir -p "$out/lib/pi" "$out/bin"
    cp -R . "$out/lib/pi/"
    makeWrapper "$out/lib/pi/pi" "$out/bin/pi" \
      --set PI_PACKAGE_DIR "$out/lib/pi" \
      --set-default PI_SKIP_VERSION_CHECK 1 \
      --set-default PI_TELEMETRY 0 \
      --set-default NODE_EXTRA_CA_CERTS "${cacert}/etc/ssl/certs/ca-bundle.crt" \
      --suffix PATH : ${lib.makeBinPath [ nodejs_22 ]} \
      --prefix PATH : ${
        lib.makeBinPath (
          [
            bash
            ripgrep
            fd
          ]
          ++ lib.optionals stdenv.hostPlatform.isLinux [
            wl-clipboard
            xclip
          ]
        )
      }
    runHook postInstall
  '';

  postFixup = lib.optionalString stdenv.hostPlatform.isLinux ''
    ${bunPatchelf}/bin/patchelf \
      --set-interpreter "$(cat "$NIX_CC/nix-support/dynamic-linker")" \
      --set-rpath "${lib.makeLibraryPath [ stdenv.cc.libc ]}" \
      "$out/lib/pi/pi"
    # Native clipboard helper is loaded with dlopen, not linked into pi.
    while IFS= read -r -d "" helper; do
      ${patchelf}/bin/patchelf \
        --set-rpath "${
          lib.makeLibraryPath [
            libxcb
            stdenv.cc.cc.lib
            stdenv.cc.libc
          ]
        }" \
        "$helper"
    done < <(find "$out/lib/pi/native" -name '*.node' -print0)
  '';

  doInstallCheck = stdenv.buildPlatform.canExecute stdenv.hostPlatform;
  nativeInstallCheckInputs = [ nodejs_22 ];
  installCheckPhase = ''
    runHook preInstallCheck
    export HOME="$TMPDIR/check-home"
    mkdir -p "$HOME"
    test "$("$out/bin/pi" --version)" = "${sources.version}"
    "$out/bin/pi" --help > "$TMPDIR/pi-help"
    grep -q -- '--provider' "$TMPDIR/pi-help"
    test -f "$out/lib/pi/theme/dark.json"
    test -f "$out/lib/pi/export-html/template.html"
    printf '%s\n' \
      '{"type":"session","version":3,"id":"nix-check","timestamp":"2026-11-07T00:00:00.000Z","cwd":"/tmp"}' \
      '{"type":"message","id":"1234abcd","parentId":null,"timestamp":"2026-11-07T00:00:01.000Z","message":{"role":"user","content":"Nix offline export check","timestamp":1794009601000}}' \
      > "$TMPDIR/check-session.jsonl"
    "$out/bin/pi" --offline --no-extensions \
      --export "$TMPDIR/check-session.jsonl" "$TMPDIR/check-export.html"
    node -e '
      const fs = require("node:fs");
      const path = require("node:path");
      const root = process.argv[1];
      function check(dir) {
        for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
          const file = path.join(dir, entry.name);
          if (entry.isDirectory()) check(file);
          else if (file.endsWith(".node")) require(file);
        }
      }
      check(root);
      const html = fs.readFileSync(process.argv[2], "utf8");
      const encoded = html.match(/<script id="session-data" type="application\/json">([^<]+)<\/script>/);
      if (!encoded) throw new Error("Missing exported session data");
      const session = JSON.parse(Buffer.from(encoded[1], "base64").toString("utf8"));
      if (session.entries[0].message.content !== "Nix offline export check") {
        throw new Error("Exported session content did not round trip");
      }
    ' "$out/lib/pi/native" "$TMPDIR/check-export.html"
    runHook postInstallCheck
  '';

  meta = {
    description = "Pi coding agent CLI (official standalone release)";
    homepage = "https://pi.dev";
    changelog = "https://github.com/earendil-works/pi/releases/tag/v${sources.version}";
    license = lib.licenses.mit;
    mainProgram = "pi";
    platforms = builtins.attrNames sources.platforms;
    sourceProvenance = [ lib.sourceTypes.binaryNativeCode ];
  };
}
