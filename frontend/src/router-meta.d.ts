import "vue-router";

declare module "vue-router" {
  interface RouteMeta {
    /** render without the workspace shell (the /intro prologue) */
    bare?: boolean;
  }
}
