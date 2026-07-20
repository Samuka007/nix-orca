{
  description = "Nix package for Orca";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs =
    { self, nixpkgs }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "aarch64-darwin"
      ];
      forAllSystems = nixpkgs.lib.genAttrs systems;
    in
    {
      packages = forAllSystems (
        system:
        let
          pkgs = import nixpkgs { inherit system; };
        in
        {
          orca-ide = pkgs.callPackage ./package.nix { };
          default = self.packages.${system}.orca-ide;
        }
      );

      overlays.default = final: _prev: {
        orca-ide = final.callPackage ./package.nix { };
      };
    };
}
