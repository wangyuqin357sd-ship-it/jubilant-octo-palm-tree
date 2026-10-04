/*
  RepackApk —— 把 aapt2 产出的 base.apk 重打一遍。只做三件事：

  1) 条目名里的反斜杠规范化成 '/'
     实测 aapt2 2.19 在 Windows 上用 `-A` 收录 assets 时，zip 条目名用的是**反斜杠**：
         assets/data\asr\model.tar.gz
     而设备上 AssetManager 是按 '/' 精确查表的（AssetManager2::Open 拼 "assets/" + path
     后做精确匹配），所以这种包装上去 getAssets().open("data/asr/model.tar.gz") 必然
     找不到 —— 页面直接白屏。必须改名。

  2) 严格按原条目的压缩方式写回
     STORED 就必须是真正的 zip method 0（带 size + CRC32），不是「用 deflate 的存块」。
     踩过的坑：.NET 的 CompressionLevel.NoCompression 和 Java 的
     Deflater.NO_COMPRESSION 都只是让 deflate 输出 stored block，条目仍然是 method 8，
     体积反而**变大**几十字节到几 KB。对 resources.arsc 这是致命的：
     targetSdkVersion >= 30 时 Android 要求 resources.arsc 必须未压缩且 4 字节对齐，
     否则直接装不上（INSTALL_PARSE_FAILED_UNEXPECTED_EXCEPTION）。
     43MB 的 model.tar.gz 也保持 STORED：本来就是 gzip，再 deflate 只会白读一遍。

  3) 追加 classes.dex

  编译：javac -encoding UTF-8 -d <out> RepackApk.java      （纯 JDK，不需要 android.jar）
  运行：java -Xmx1g RepackApk <base.apk> <classes.dex> <out.apk>
*/
import java.io.BufferedOutputStream;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.Enumeration;
import java.util.zip.CRC32;
import java.util.zip.Deflater;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;
import java.util.zip.ZipOutputStream;

public class RepackApk {

    public static void main(String[] args) throws Exception {
        if (args.length != 3) {
            System.err.println("usage: RepackApk <base.apk> <classes.dex> <out.apk>");
            System.exit(2);
        }
        File baseApk = new File(args[0]);
        File dexFile = new File(args[1]);
        File outApk  = new File(args[2]);
        if (!baseApk.isFile()) { System.err.println("missing " + baseApk); System.exit(2); }
        if (!dexFile.isFile()) { System.err.println("missing " + dexFile); System.exit(2); }
        if (outApk.exists() && !outApk.delete()) {
            System.err.println("cannot delete " + outApk); System.exit(2);
        }

        int renamed = 0, stored = 0, deflated = 0, skipped = 0;
        ZipFile zf = new ZipFile(baseApk);
        ZipOutputStream zo = new ZipOutputStream(
                new BufferedOutputStream(new FileOutputStream(outApk), 1 << 16));
        try {
            Enumeration<? extends ZipEntry> en = zf.entries();
            while (en.hasMoreElements()) {
                ZipEntry e = en.nextElement();
                String name = e.getName();
                if (name.indexOf('\\') >= 0) { name = name.replace('\\', '/'); renamed++; }
                if (name.equals("classes.dex")) { skipped++; continue; }

                byte[] data = readAll(zf.getInputStream(e), e.getSize());

                ZipEntry ne = new ZipEntry(name);
                if (e.getTime() != -1) ne.setTime(e.getTime());
                if (e.getMethod() == ZipEntry.STORED) {
                    putStored(zo, ne, data);
                    stored++;
                } else {
                    zo.setLevel(Deflater.DEFAULT_COMPRESSION);
                    zo.putNextEntry(ne);
                    zo.write(data);
                    zo.closeEntry();
                    deflated++;
                }
            }

            byte[] dex = readAll(new java.io.FileInputStream(dexFile), dexFile.length());
            zo.setLevel(Deflater.DEFAULT_COMPRESSION);
            zo.putNextEntry(new ZipEntry("classes.dex"));
            zo.write(dex);
            zo.closeEntry();
        } finally {
            try { zo.close(); } catch (IOException ignored) { }
            try { zf.close(); } catch (IOException ignored) { }
        }

        System.out.println("RepackApk: entries renamed=" + renamed
                + " stored=" + stored + " deflated=" + deflated
                + " skippedDex=" + skipped
                + " out=" + outApk.length() + " bytes");
    }

    /** 真正的 zip STORED：method 0 + size/compressedSize/CRC32 都要预先填好。 */
    private static void putStored(ZipOutputStream zo, ZipEntry ne, byte[] data) throws IOException {
        CRC32 crc = new CRC32();
        crc.update(data, 0, data.length);
        ne.setMethod(ZipEntry.STORED);
        ne.setSize(data.length);
        ne.setCompressedSize(data.length);
        ne.setCrc(crc.getValue());
        zo.setLevel(Deflater.NO_COMPRESSION);   // 防止 Deflater 插手
        zo.putNextEntry(ne);
        zo.write(data);
        zo.closeEntry();
    }

    private static byte[] readAll(InputStream in, long hint) throws IOException {
        try {
            int cap = (hint > 0 && hint < Integer.MAX_VALUE) ? (int) hint : 8192;
            ByteArrayOutputStream bos = new ByteArrayOutputStream(Math.max(cap, 8192));
            byte[] buf = new byte[1 << 16];
            int n;
            while ((n = in.read(buf)) > 0) bos.write(buf, 0, n);
            return bos.toByteArray();
        } finally {
            try { in.close(); } catch (IOException ignored) { }
        }
    }
}