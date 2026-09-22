{
  description = "Agnostic media player daemon — queue YouTube/TikTok/audiobooks, drive from Claude Code hooks";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };

        # Runtime binaries the backends shell out to. yt-dlp resolves
        # YouTube/TikTok; playerctl (Linux/MPRIS) drives system-wide play/pause
        # for the empty-queue path. All put on the wrapped scripts' PATH.
        runtimeDeps = [ pkgs.mpv pkgs.yt-dlp pkgs.tailscale ]
          ++ pkgs.lib.optional pkgs.stdenv.hostPlatform.isLinux pkgs.playerctl;

        mediaplayer = pkgs.python3Packages.buildPythonApplication {
          pname = "mediaplayer";
          version = "0.1.0";
          src = ./.;
          pyproject = true;

          build-system = [ pkgs.python3Packages.setuptools ];
          # No Python runtime deps (stdlib only).
          nativeBuildInputs = [ pkgs.makeWrapper ];

          pythonImportsCheck = [ "mediaplayer" ];
          doCheck = true;
          checkPhase = ''
            runHook preCheck
            python tests/test_controller.py
            python tests/test_system_control.py
            python tests/test_system_routing.py
            python tests/test_autostart.py
            python tests/test_http_api.py
            python tests/test_tailscale_endpoint.py
            runHook postCheck
          '';

          # Prepend mpv + yt-dlp so playback works regardless of the user's PATH.
          postFixup = ''
            for prog in mediactl mediaplayer-daemon; do
              wrapProgram $out/bin/$prog \
                --prefix PATH : ${pkgs.lib.makeBinPath runtimeDeps}
            done
          '';

          meta = {
            description = "Agnostic media player daemon (YouTube/TikTok/audiobooks; Spotify pinned)";
            homepage = "https://github.com/hedonicadapter/media-player";
            mainProgram = "mediactl";
          };
        };
      in
      {
        packages.default = mediaplayer;
        packages.mediaplayer = mediaplayer;

        # `nix run github:hedonicadapter/media-player -- <cmd>` -> mediactl
        apps.default = {
          type = "app";
          program = "${mediaplayer}/bin/mediactl";
        };
        # `nix run github:hedonicadapter/media-player#daemon`
        apps.daemon = {
          type = "app";
          program = "${mediaplayer}/bin/mediaplayer-daemon";
        };

        devShells.default = pkgs.mkShell {
          packages = [ pkgs.python3 pkgs.mpv pkgs.yt-dlp pkgs.tailscale ]
            ++ pkgs.lib.optional pkgs.stdenv.hostPlatform.isLinux pkgs.playerctl;
        };
      });
}
