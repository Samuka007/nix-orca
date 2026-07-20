{
  lib,
  appimageTools,
  fetchurl,
  python3,
  stdenv,
  stdenvNoCC,
  unzip,
}:

let
  pname = "orca-ide";
  version = "1.4.146";
  system = stdenv.hostPlatform.system;

  sources = {
    x86_64-linux = {
      url = "https://github.com/stablyai/orca/releases/download/v${version}/orca-linux.AppImage";
      hash = "sha256-/DQnU0U4XyOAxYX7J81gCJP2OgaLxTARr4kUpvqdT8k=";
    };
    aarch64-linux = {
      url = "https://github.com/stablyai/orca/releases/download/v${version}/orca-linux-arm64.AppImage";
      hash = "sha256-ZmnwdLtJU59Ck6l27oo1OSLOtUW5OX/hUkx5bCG35rc=";
    };
    aarch64-darwin = {
      url = "https://github.com/stablyai/orca/releases/download/v${version}/Orca-${version}-arm64-mac.zip";
      hash = "sha256-CQ2QgpBJWcOCyrrlmrrgSIH2F7a7em/mnziEqy/pu4Q=";
    };
  };

  src = fetchurl (sources.${system} or (throw "orca-ide: unsupported system ${system}"));

  commonMeta = {
    description = "ADE for working with a fleet of parallel coding agents";
    homepage = "https://github.com/stablyai/orca";
    changelog = "https://github.com/stablyai/orca/releases/tag/v${version}";
    license = lib.licenses.mit;
    platforms = builtins.attrNames sources;
    sourceProvenance = [ lib.sourceTypes.binaryNativeCode ];
  };

  linuxPackage =
    let
      appimageContents = appimageTools.extractType2 {
        inherit pname version src;
      };
      python = python3.withPackages (packages: [ packages.pygobject3 ]);
    in
    appimageTools.wrapType2 {
      inherit pname version src;

      extraPkgs = pkgs: [
        pkgs.at-spi2-core
        pkgs.xclip
        pkgs.xdotool
        pkgs.xvfb
        python
      ];

      extraInstallCommands = ''
        mv $out/bin/orca-ide $out/bin/orca-ide-gui

        cat > $out/bin/orca-ide <<'EOF'
        #!${stdenv.shell}
        set -euo pipefail

        script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
        export ORCA_NODE_OPTIONS="''${NODE_OPTIONS-}"
        export ORCA_NODE_REPL_EXTERNAL_MODULE="''${NODE_REPL_EXTERNAL_MODULE-}"
        unset NODE_OPTIONS
        unset NODE_REPL_EXTERNAL_MODULE

        ELECTRON_RUN_AS_NODE=1 exec "$script_dir/orca-ide-gui" \
          "${appimageContents}/resources/app.asar.unpacked/out/cli/index.js" "$@"
        EOF
        chmod 755 $out/bin/orca-ide

        install -Dm444 ${appimageContents}/orca-ide.desktop \
          $out/share/applications/orca-ide.desktop
        substituteInPlace $out/share/applications/orca-ide.desktop \
          --replace-fail "Exec=AppRun --no-sandbox %U" "Exec=orca-ide-gui --no-sandbox %U"
        cp -r ${appimageContents}/usr/share/icons $out/share/
      '';

      meta = commonMeta // {
        mainProgram = "orca-ide";
      };
    };

  darwinPackage = stdenvNoCC.mkDerivation {
    inherit pname version src;

    nativeBuildInputs = [ unzip ];
    sourceRoot = ".";

    installPhase = ''
      runHook preInstall

      mkdir -p $out/Applications $out/bin
      cp -R Orca.app $out/Applications/
      ln -s $out/Applications/Orca.app/Contents/Resources/bin/orca $out/bin/orca
      ln -s $out/Applications/Orca.app/Contents/MacOS/Orca $out/bin/orca-ide-gui

      runHook postInstall
    '';

    # Preserve the upstream notarized bundle and its code signatures.
    dontFixup = true;

    meta = commonMeta // {
      mainProgram = "orca";
    };
  };
in
if stdenv.hostPlatform.isDarwin then darwinPackage else linuxPackage
