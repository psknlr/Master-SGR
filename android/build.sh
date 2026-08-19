#!/usr/bin/env bash
# =============================================================================
#  国医大师孙光荣中医知识图谱 · Android 打包脚本
#  Sun Guangrong TCM Knowledge Graph — Android build & signing script
#
#  用 Android SDK 自带的 aapt2 / d8 / zipalign / apksigner 直接产出已签名 APK，
#  不依赖 Gradle 与任何第三方库，离线可复现。
#
#  用法：
#      ANDROID_HOME=/path/to/android-sdk ./build.sh
#  产物：
#      android/out/SunGuangrong-TCM-KnowledgeGraph-v<versionName>.apk （已签名、已对齐）
# =============================================================================
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

ANDROID_HOME="${ANDROID_HOME:-$HOME/android-sdk}"
PLATFORM_VER="${PLATFORM_VER:-android-34}"

# 取已安装的最新 build-tools。注意 34.0.0 自带的 d8(R8 8.2.2) 无法处理
# JDK 21 javac 产生的匿名内部类，需 35.0.0 及以上。
if [ -z "${BUILD_TOOLS_VER:-}" ]; then
  BUILD_TOOLS_VER="$(ls -1 "$ANDROID_HOME/build-tools" 2>/dev/null | sort -V | tail -1)"
fi
BT="$ANDROID_HOME/build-tools/$BUILD_TOOLS_VER"
ANDROID_JAR="$ANDROID_HOME/platforms/$PLATFORM_VER/android.jar"

[ -x "$BT/aapt2" ]      || { echo "缺少 aapt2：$BT/aapt2"; exit 1; }
[ -f "$ANDROID_JAR" ]   || { echo "缺少 android.jar：$ANDROID_JAR"; exit 1; }
echo "    build-tools $BUILD_TOOLS_VER · platform $PLATFORM_VER · $(javac -version 2>&1 | tail -1)"

SRC=app/src/main
OUT=out
WORK=$OUT/work
VERSION_NAME="$(sed -n 's/.*android:versionName="\([^"]*\)".*/\1/p' "$SRC/AndroidManifest.xml" | head -1)"
APK_NAME="SunGuangrong-TCM-KnowledgeGraph-v${VERSION_NAME}"

# ---- 签名密钥（首次运行自动生成，之后复用，保证升级签名一致） ----------------
KEYSTORE="${KEYSTORE:-$HERE/keystore/sgr-kg-release.jks}"
KS_PASS="${KS_PASS:-sgrkg2024}"
KEY_ALIAS="${KEY_ALIAS:-sgrkg}"
KEY_PASS="${KEY_PASS:-$KS_PASS}"

rm -rf "$WORK"; mkdir -p "$WORK/compiled" "$WORK/classes" "$WORK/gen" "$OUT"

echo "==> [1/6] aapt2 compile 资源"
"$BT/aapt2" compile --dir "$SRC/res" -o "$WORK/compiled/res.zip"

echo "==> [2/6] aapt2 link （含 assets，生成 R.java）"
"$BT/aapt2" link \
  -o "$WORK/base.apk" \
  -I "$ANDROID_JAR" \
  --manifest "$SRC/AndroidManifest.xml" \
  -A "$SRC/assets" \
  --java "$WORK/gen" \
  --auto-add-overlay \
  --no-version-vectors \
  "$WORK/compiled/res.zip"

echo "==> [3/6] javac 编译 Java 源码"
find "$SRC/java" "$WORK/gen" -name '*.java' > "$WORK/sources.txt"
javac -source 8 -target 8 -nowarn -encoding UTF-8 \
  -bootclasspath "$ANDROID_JAR" -classpath "$ANDROID_JAR" \
  -d "$WORK/classes" @"$WORK/sources.txt" 2>&1 | grep -v 'bootstrap class path' || true

echo "==> [4/6] d8 生成 dex"
jar cf "$WORK/classes.jar" -C "$WORK/classes" .
"$BT/d8" --release --min-api 21 --lib "$ANDROID_JAR" \
  --output "$WORK" "$WORK/classes.jar"

echo "==> [5/6] 合并 dex 并对齐"
cp "$WORK/base.apk" "$WORK/unaligned.apk"
( cd "$WORK" && zip -q -X "unaligned.apk" classes.dex )
rm -f "$WORK/aligned.apk"
# resources.arsc 必须以「不压缩且 4 字节对齐」的形式存放（Android 11+ 要求）
"$BT/zipalign" -p -f 4 "$WORK/unaligned.apk" "$WORK/aligned.apk"

echo "==> [6/6] 签名"
if [ ! -f "$KEYSTORE" ]; then
  echo "    首次构建：生成发布密钥 $KEYSTORE"
  mkdir -p "$(dirname "$KEYSTORE")"
  keytool -genkeypair -v \
    -keystore "$KEYSTORE" -storetype PKCS12 -storepass "$KS_PASS" \
    -alias "$KEY_ALIAS" -keypass "$KEY_PASS" \
    -keyalg RSA -keysize 4096 -validity 10950 \
    -dname "CN=Sun Guangrong TCM Knowledge Graph, OU=IMPF-AI Institute, O=Tian Jianhui Team x IMPF-AI Institute, L=Shanghai, C=CN" \
    >/dev/null 2>&1
fi

"$BT/apksigner" sign \
  --ks "$KEYSTORE" --ks-pass "pass:$KS_PASS" \
  --ks-key-alias "$KEY_ALIAS" --key-pass "pass:$KEY_PASS" \
  --v1-signing-enabled true --v2-signing-enabled true --v3-signing-enabled true --v4-signing-enabled false \
  --min-sdk-version 21 --max-sdk-version 34 \
  --out "$OUT/$APK_NAME.apk" \
  "$WORK/aligned.apk"

"$BT/apksigner" verify --print-certs --verbose "$OUT/$APK_NAME.apk"

echo
echo "✔ 构建完成：$HERE/$OUT/$APK_NAME.apk"
ls -lh "$OUT/$APK_NAME.apk"
