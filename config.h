#include <X11/XF86keysym.h>

#define XF86XK_AudioMicMute 0x1008FFB2
#define XF86XK_PrintScreenDWM 0x0000ff61

/* See LICENSE file for copyright and license details. */

/* appearance */
static const unsigned int borderpx       = 8;    /* border pixel of windows */
static const unsigned int gappx          = 12;   /* gap pixel between windows */
static const unsigned int snap           = 32;   /* snap pixel */
static const unsigned int systraypinning = 0;    /* 0: sloppy systray follows selected monitor, >0: pin systray to monitor X */
static const unsigned int systrayonleft  = 0;    /* 0: systray in the right corner, >0: systray on left of status text */
static const unsigned int systrayspacing = 10;   /* systray spacing */
static const int systraypinningfailfirst = 1;    /* 1: if pinning fails, display systray on the first monitor, False: display systray on the last monitor*/
static const int showsystray             = 1;    /* 0 means no systray */
static const int showbar                 = 1;    /* 0 means no bar */
static const int topbar                  = 1;    /* 0 means bottom bar */
static const char *fonts[]               = { "monospace:size = 12", "yiang_nerd_font:size:14", "Noto Sans CJK JP:size = 10", "FiraCode Nerd Font:size:20" };
static const char dmenufont[]            = "monospace:size = 14";
static const char col_gray1[]            = "#222222";
static const char col_gray2[]            = "#444444";
static const char col_gray3[]            = "#bbbbbb";
static const char col_gray4[]            = "#eeeeee";
static const char col_cyan[]             = "#005577";

static const char col_foreground[]    = "#333";
static const char col_background[]    = "#c2b594";
static const char col_in_background[] = "#ebdbb2";
static const char col_no_border[]     = "#fffae8";
static const char col_lightborder[]   = "#007cff";
static const char col_tag_sel_fore[]  = "#000000";
static const char col_tag_sel_back[]  = "#ebdbb2";
static const char col_tag_nor_fore[]  = "#cecece";
static const char col_tag_nor_back[]  = "#404040";
static const char col_title_back[]    = "#ddcfab";

static const char *colors[][3]      = {
    /*                     fg                 bg                  border   */
    [SchemeNorm]       = { col_foreground   , col_in_background , "#999999"       } ,
    [SchemeSel]        = { col_foreground   , col_background    , col_lightborder } ,
    [SchemeStatus]     = { col_gray3        , col_gray1         , "#000000"       } , // Statusbar right {text            , background , not used but cannot be empty }
    [SchemeTagsSel]    = { col_tag_sel_fore , col_tag_sel_back  , "#000000"       } , // Tagbar left selected {text       , background , not used but cannot be empty }
    [SchemeTagsNorm]   = { col_tag_nor_fore , col_tag_nor_back  , "#000000"       } , // Tagbar left unselected {text     , background , not used but cannot be empty }
    [SchemeTagsUrgent] = { "#FFFFFF"        , "#ff6f00"         , "#000000"       } , // Tagbar left unselected {text     , background , not used but cannot be empty }
    [SchemeInfoSel]    = { col_tag_sel_fore , col_title_back    , "#000000"       } , // infobar middle  selected {text   , background , not used but cannot be empty }
    [SchemeInfoNorm]   = { col_gray3        , col_title_back    , "#000000"       } , // infobar middle  unselected {text , background , not used but cannot be empty }
};

static const char *tags[] = { "1", "2", "3", "4", "5", "6", "7", "8", "9" };
static const Rule rules[] = {
    /* class      instance    title       tags mask     isfloating   monitor */
    { "Gimp",     NULL,       NULL,       0,            1,           -1 },
    { "Firefox",  NULL,       NULL,       1 << 8,       0,           -1 },
};

/* layout(s) */
static const float mfact        = 0.55; /* factor of master area size [0.05..0.95] */
static const int   nmaster        = 1;    /* number of clients in master area */
static const int   resizehints    = 1;    /* 1 means respect size hints in tiled resizals */
static const int   lockfullscreen = 1; /* 1 will force focus on the fullscreen window */

static const Layout layouts[] = {
    /* symbol     arrange function */
    { "[]=",      tile },    /* first entry is default */
    { "><>",      NULL },    /* no layout function means floating behavior */
    { "[M]",      monocle },
};

/* key definitions */
/* Set to Super Key */
#define MODKEY Mod4Mask
#define TAGKEYS(KEY,TAG) \
    { MODKEY,                       KEY,      view,           {.ui = 1 << TAG} }, \
    { MODKEY|ControlMask,           KEY,      toggleview,     {.ui = 1 << TAG} }, \
    { MODKEY|Mod1Mask,             KEY,      tag,            {.ui = 1 << TAG} }, \
    { MODKEY|ControlMask|ShiftMask, KEY,      toggletag,      {.ui = 1 << TAG} },

/* helper for spawning shell commands in the pre dwm-5.0 fashion */
#define SHCMD(cmd) { .v = (const char*[]){ "/bin/sh", "-c", cmd, NULL } }

/* commands */
static char dmenumon[2] = "0"; /* component of dmenucmd, manipulated in spawn() */
static const char *dmenucmd[] = { "dmenu_run", "-m", dmenumon, "-fn", dmenufont, "-nb", col_gray1, "-nf", col_gray3, "-sb", col_cyan, "-sf", col_gray4, NULL };
static const char *termcmd[]  = { "alacritty", NULL };

static const Key keys[] = {
    /* modifier                     key        function        argument */
    { MODKEY,                       XK_e,      spawn,          {.v = dmenucmd } },
    { MODKEY|Mod1Mask,              XK_e,      spawn,          SHCMD("dmenu_o") },
    { MODKEY,                       XK_Return, spawn,          {.v = termcmd } },
    { MODKEY,                       XK_j,      focusstack,     {.i = +1 } },
    { MODKEY,                       XK_k,      focusstack,     {.i = -1 } },

    // { MODKEY,                       XK_b,      togglebar,      {0} },
    // { MODKEY,                       XK_i,      incnmaster,     {.i = +1 } },
    // { MODKEY,                       XK_d,      incnmaster,     {.i = -1 } },


    /* Volume Keys */
    /* vol - script file - ~/scripts/vol */
    { 0         , XF86XK_AudioMute        , spawn , SHCMD("vol toggleMute") },
    { 0         , XF86XK_AudioRaiseVolume , spawn , SHCMD("vol up") },
    { 0         , XF86XK_AudioLowerVolume , spawn , SHCMD("vol down") },
    { 0         , XF86XK_AudioMicMute     , spawn , SHCMD("vol toggleMuteMic") },
    { ShiftMask , XF86XK_AudioMute        , spawn , SHCMD("vol default") },
    { ShiftMask , XF86XK_AudioMute        , spawn , SHCMD("vol default") },
    { 0         , XK_Pause                , spawn , SHCMD("vol pause") },
    { 0         , XF86XK_PrintScreenDWM   , spawn , SHCMD("capt") },

    { 0         , XF86XK_AudioNext   , spawn , SHCMD("vol next") },
    { 0         , XF86XK_AudioPrev   , spawn , SHCMD("vol prev") },

    /* bri - script file - ~/scripts/bri */
    /* normal keyboard don't have bri key, use shift+audio to simulate */
    { ShiftMask        , XF86XK_AudioRaiseVolume  , spawn         , SHCMD("bri up") },
    { ShiftMask        , XF86XK_AudioLowerVolume  , spawn         , SHCMD("bri down") },
    { 0                , XF86XK_MonBrightnessUp   , spawn         , SHCMD("bri up") },
    { 0                , XF86XK_MonBrightnessDown , spawn         , SHCMD("bri down") },
    { MODKEY           , XK_m                     , zoom          , {0} },
    { MODKEY           , XK_Tab                   , view          , {0} },
    { MODKEY           , XK_q                     , killclient    , {0} },
    { MODKEY|ShiftMask , XK_e                     , spawn         , SHCMD("exit_dwm") },
    { MODKEY           , XK_f                     , togglefullscr , {0} },
    { MODKEY           , XK_0                     , view          , {.ui = ~0 } },

    // { MODKEY|ShiftMask,             XK_space,  togglefloating, {0} },
    // { MODKEY|ShiftMask,             XK_0,      tag,            {.ui = ~0 } },
    // { MODKEY,                       XK_h,      setmfact,       {.f = -0.05} },
    // { MODKEY,                       XK_l,      setmfact,       {.f = +0.05} },
    // { MODKEY,                       XK_t,      setlayout,      {.v = &layouts[0]} },
    // { MODKEY|ShiftMask,             XK_f,      setlayout,      {.v = &layouts[1]} },
    // { MODKEY,                       XK_p,      setlayout,      {.v = &layouts[2]} },
    // { MODKEY,                       XK_space,  setlayout,      {0} },

    { MODKEY,                       XK_comma,  focusmon,       {.i = -1 } },
    { MODKEY,                       XK_period, focusmon,       {.i = +1 } },
    { MODKEY|ShiftMask,             XK_comma,  tagmon,         {.i = -1 } },
    { MODKEY|ShiftMask,             XK_period, tagmon,         {.i = +1 } },
    { MODKEY|ShiftMask,             XK_q,      quit,           {0} },

    TAGKEYS(XK_1, 0)
    TAGKEYS(XK_2, 1)
    TAGKEYS(XK_3, 2)
    TAGKEYS(XK_4, 3)
    TAGKEYS(XK_5, 4)
    TAGKEYS(XK_6, 5)
    TAGKEYS(XK_7, 6)
    TAGKEYS(XK_8, 7)
    TAGKEYS(XK_9, 8)
};

/* button definitions */
/* click can be ClkTagBar, ClkLtSymbol, ClkStatusText, ClkWinTitle, ClkClientWin, or ClkRootWin */
/**
 * Button1 = Left Click
 * Button2 = Middle Click
 * Button3 = Right Click
 * Button4 = Scroll up
 * Button5 = Scroll down
 */

static const Button buttons[] = {
	/* click                event mask      button          function        argument */
	// { ClkLtSymbol,          0,              Button1,        setlayout,      {0} },
	// { ClkLtSymbol,          0,              Button3,        setlayout,      {.v = &layouts[2]} },
	{ ClkTagBar,            MODKEY,         Button1,        tag,            {0} },
	{ ClkTagBar,            MODKEY,         Button3,        toggletag,      {0} },
	{ ClkWinTitle,          0,              Button2,        zoom,           {0} },
	/* { ClkStatusText,        0,              Button2,        spawn,          {.v = termcmd } }, */
	{ ClkClientWin,         MODKEY,         Button1,        movemouse,      {0} },
	{ ClkClientWin,         MODKEY,         Button2,        togglefloating, {0} },
	{ ClkClientWin,         MODKEY,         Button3,        resizemouse,    {0} },
	{ ClkTagBar,            0,              Button1,        view,           {0} },
	{ ClkTagBar,            0,              Button3,        toggleview,     {0} },
	{ ClkTagBar,            MODKEY,         Button1,        tag,            {0} },
	{ ClkTagBar,            MODKEY,         Button3,        toggletag,      {0} },
};
