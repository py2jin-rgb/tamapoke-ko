#pragma once
#include <stdint.h>
#include <stddef.h>
#include <string.h>

// Small Cheonjiin (천지인) Hangul composer for TamaPoke nickname input.
// The committed buffer is UTF-8. Current Hangul syllable is kept separately
// until it is committed, so backspace and final-consonant carry work correctly.

struct HangulComposer {
  int8_t L = -1;
  int8_t V = -1;
  uint8_t T = 0;
  uint8_t vseq[5] = {0};
  uint8_t vlen = 0;
  int8_t lastGroup = -1;
  uint8_t lastSlot = 0;
  static const uint8_t MAX_NAME_CP = 8;

  void resetCompose() { L=-1; V=-1; T=0; vlen=0; lastGroup=-1; lastSlot=0; }

  static uint8_t utf8Count(const char *s) {
    uint8_t n=0;
    for (const uint8_t *p=(const uint8_t*)s; *p; p++) if ((*p & 0xC0) != 0x80) n++;
    return n;
  }

  static bool appendCp(char *buf, size_t cap, uint32_t cp) {
    if (!buf || cap < 2) return false;
    size_t n=strlen(buf); uint8_t b[4]; uint8_t k=0;
    if (cp <= 0x7F) { b[0]=cp; k=1; }
    else if (cp <= 0x7FF) { b[0]=0xC0|(cp>>6); b[1]=0x80|(cp&0x3F); k=2; }
    else if (cp <= 0xFFFF) { b[0]=0xE0|(cp>>12); b[1]=0x80|((cp>>6)&0x3F); b[2]=0x80|(cp&0x3F); k=3; }
    else { b[0]=0xF0|(cp>>18); b[1]=0x80|((cp>>12)&0x3F); b[2]=0x80|((cp>>6)&0x3F); b[3]=0x80|(cp&0x3F); k=4; }
    if (n+k >= cap) return false;
    for (uint8_t i=0;i<k;i++) buf[n+i]=(char)b[i];
    buf[n+k]=0; return true;
  }

  static void popUtf8(char *buf) {
    size_t n=strlen(buf); if (!n) return;
    size_t i=n-1; while (i>0 && (((uint8_t)buf[i] & 0xC0) == 0x80)) i--;
    buf[i]=0;
  }

  static uint32_t compatL(int8_t l) {
    static const uint16_t cp[19]={0x3131,0x3132,0x3134,0x3137,0x3138,0x3139,0x3141,0x3142,0x3143,0x3145,0x3146,0x3147,0x3148,0x3149,0x314A,0x314B,0x314C,0x314D,0x314E};
    return (l>=0&&l<19)?cp[l]:0;
  }
  static uint32_t compatV(int8_t v) { return (v>=0&&v<21)?(0x314F+v):0; }
  uint32_t currentCp() const {
    if (L>=0&&V>=0) return 0xAC00u+(uint32_t)((L*21+V)*28+T);
    if (L>=0) return compatL(L); if (V>=0) return compatV(V); return 0;
  }

  bool commit(char *buf,size_t cap) {
    uint32_t cp=currentCp(); if(!cp){resetCompose();return true;}
    if(utf8Count(buf)>=MAX_NAME_CP) return false;
    if(!appendCp(buf,cap,cp)) return false;
    resetCompose(); return true;
  }

  void preview(const char *committed,char *out,size_t cap) const {
    if(!cap)return; strncpy(out,committed?committed:"",cap-1); out[cap-1]=0;
    if(L>=0&&V>=0) appendCp(out,cap,currentCp());
    else {
      if(L>=0) appendCp(out,cap,compatL(L));
      if(V>=0) appendCp(out,cap,compatV(V));
      else if(vlen) for(uint8_t i=0;i<vlen;i++) appendCp(out,cap,vseq[i]==0?0x318D:(vseq[i]==1?0x3161:0x3163));
    }
  }

  // vowel token: 0=ㆍ, 1=ㅡ, 2=ㅣ
  static int8_t vowelFor(const uint8_t *s,uint8_t n) {
    struct VM{uint8_t n,a[5];int8_t v;};
    static const VM m[]={
      {1,{2,0,0,0,0},20},{1,{1,0,0,0,0},18},{2,{2,0,0,0,0},0},{3,{2,0,0,0,0},2},
      {2,{0,2,0,0,0},4},{3,{0,0,2,0,0},6},{2,{0,1,0,0,0},8},{3,{0,0,1,0,0},12},
      {2,{1,0,0,0,0},13},{3,{1,0,0,0,0},17},{3,{2,0,2,0,0},1},{4,{2,0,0,2,0},3},
      {3,{0,2,2,0,0},5},{4,{0,0,2,2,0},7},{3,{0,1,2,0,0},11},{4,{0,1,2,0,0},9},
      {5,{0,1,2,0,2},10},{3,{1,0,2,0,0},16},{4,{1,0,0,2,0},14},{5,{1,0,0,2,2},15},{2,{1,2,0,0,0},19}
    };
    for(unsigned i=0;i<sizeof(m)/sizeof(m[0]);i++){if(m[i].n!=n)continue;bool ok=true;for(uint8_t j=0;j<n;j++)if(m[i].a[j]!=s[j]){ok=false;break;}if(ok)return m[i].v;}
    return -1;
  }

  static bool vowelPrefix(const uint8_t *s,uint8_t n) {
    static const uint8_t q[][6]={
      {1,2,0,0,0,0},{1,1,0,0,0,0},{2,2,0,0,0,0},{3,2,0,0,0,0},{2,0,2,0,0,0},{3,0,0,2,0,0},
      {2,0,1,0,0,0},{3,0,0,1,0,0},{2,1,0,0,0,0},{3,1,0,0,0,0},{3,2,0,2,0,0},{4,2,0,0,2,0},
      {3,0,2,2,0,0},{4,0,0,2,2,0},{3,0,1,2,0,0},{4,0,1,2,0,0},{5,0,1,2,0,2},{3,1,0,2,0,0},
      {4,1,0,0,2,0},{5,1,0,0,2,2},{2,1,2,0,0,0}
    };
    for(unsigned i=0;i<sizeof(q)/sizeof(q[0]);i++){uint8_t len=q[i][0];if(n>len)continue;bool ok=true;for(uint8_t j=0;j<n;j++)if(q[i][j+1]!=s[j]){ok=false;break;}if(ok)return true;}return false;
  }

  static int8_t lToT(int8_t l){static const int8_t t[19]={1,2,4,7,-1,8,16,17,-1,19,20,21,22,-1,23,24,25,26,27};return(l>=0&&l<19)?t[l]:-1;}
  static int8_t tToL(uint8_t t){switch(t){case 1:return 0;case 2:return 1;case 4:return 2;case 7:return 3;case 8:return 5;case 16:return 6;case 17:return 7;case 19:return 9;case 20:return 10;case 21:return 11;case 22:return 12;case 23:return 14;case 24:return 15;case 25:return 16;case 26:return 17;case 27:return 18;default:return -1;}}
  static uint8_t combineT(uint8_t a,int8_t l){int8_t b=lToT(l);if(a==1&&b==19)return 3;if(a==4&&b==22)return 5;if(a==4&&b==27)return 6;if(a==8&&b==1)return 9;if(a==8&&b==16)return 10;if(a==8&&b==17)return 11;if(a==8&&b==19)return 12;if(a==8&&b==25)return 13;if(a==8&&b==26)return 14;if(a==8&&b==27)return 15;if(a==17&&b==19)return 18;return 0;}
  static bool splitT(uint8_t t,uint8_t &f,int8_t &s){switch(t){case 3:f=1;s=9;return true;case 5:f=4;s=12;return true;case 6:f=4;s=18;return true;case 9:f=8;s=0;return true;case 10:f=8;s=6;return true;case 11:f=8;s=7;return true;case 12:f=8;s=9;return true;case 13:f=8;s=16;return true;case 14:f=8;s=17;return true;case 15:f=8;s=18;return true;case 18:f=17;s=9;return true;default:return false;}}
  static int8_t groupAt(uint8_t g,uint8_t p){static const int8_t a[7][2]={{0,15},{2,5},{3,16},{7,17},{9,18},{12,14},{11,6}};return g<7?a[g][p&1]:-1;}
  static bool lInGroup(int8_t l,uint8_t g,uint8_t &p){if(g>=7)return false;if(groupAt(g,0)==l){p=0;return true;}if(groupAt(g,1)==l){p=1;return true;}return false;}

  void inputGroup(uint8_t g,char *buf,size_t cap){
    if(g>=7)return;
    if(L<0){L=groupAt(g,0);lastGroup=g;lastSlot=1;return;}
    if(V<0){uint8_t p=0;if(lastSlot==1&&lastGroup==(int8_t)g&&lInGroup(L,g,p))L=groupAt(g,p+1);else L=groupAt(g,0);lastGroup=g;lastSlot=1;return;}
    if(T==0){int8_t c=groupAt(g,0),jt=lToT(c);if(jt>0){T=(uint8_t)jt;lastGroup=g;lastSlot=2;}else if(commit(buf,cap)){L=c;lastGroup=g;lastSlot=1;}return;}
    if(lastSlot==2&&lastGroup==(int8_t)g){int8_t cl=tToL(T);uint8_t p=0;if(cl>=0&&lInGroup(cl,g,p)){int8_t nx=groupAt(g,p+1),nt=lToT(nx);if(nt>0){T=(uint8_t)nt;return;}}}
    int8_t c=groupAt(g,0);uint8_t j=combineT(T,c);if(j){T=j;lastGroup=g;lastSlot=2;return;}if(commit(buf,cap)){L=c;lastGroup=g;lastSlot=1;}
  }

  void inputDouble(){auto d=[](int8_t l)->int8_t{switch(l){case 0:return 1;case 3:return 4;case 7:return 8;case 9:return 10;case 12:return 13;default:return l;}};if(L>=0&&V<0){L=d(L);lastGroup=-1;lastSlot=1;return;}if(L>=0&&V>=0&&T>0){int8_t l=tToL(T);if(l<0)return;int8_t x=d(l),nt=lToT(x);if(nt>0)T=(uint8_t)nt;lastGroup=-1;lastSlot=2;}}

  void inputVowel(uint8_t tok,char *buf,size_t cap){
    if(tok>2)return;
    if(L>=0&&V>=0&&T>0){uint8_t f=0;int8_t moved=-1;if(splitT(T,f,moved))T=f;else{moved=tToL(T);T=0;}if(!commit(buf,cap))return;L=moved>=0?moved:11;}else if(L<0)L=11;
    uint8_t ns[5];uint8_t nn=vlen;for(uint8_t i=0;i<vlen&&i<5;i++)ns[i]=vseq[i];if(nn<5)ns[nn++]=tok;
    if(vowelPrefix(ns,nn)){for(uint8_t i=0;i<nn;i++)vseq[i]=ns[i];vlen=nn;int8_t nv=vowelFor(vseq,vlen);if(nv>=0)V=nv;lastGroup=-1;lastSlot=0;return;}
    if(V>=0){if(!commit(buf,cap))return;L=11;vseq[0]=tok;vlen=1;V=vowelFor(vseq,vlen);lastGroup=-1;lastSlot=0;}
  }

  void backspace(char *buf){if(T>0){T=0;lastGroup=-1;lastSlot=0;return;}if(vlen>0){vlen--;V=vlen?vowelFor(vseq,vlen):-1;lastGroup=-1;lastSlot=0;return;}if(L>=0){L=-1;lastGroup=-1;lastSlot=0;return;}popUtf8(buf);}
};
