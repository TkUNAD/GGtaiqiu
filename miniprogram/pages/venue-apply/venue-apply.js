const publicApi = require('../../utils/publicApi');



Page({

  data: {

    phone: '',

    clubName: '',

    password: '',

    confirm: '',

    captchaId: '',

    captchaImg: '',

    captchaCode: '',

    submitting: false,

  },



  onLoad() {

    this.loadCaptcha();

  },



  async loadCaptcha() {

    try {

      const d = await publicApi.getCaptcha();

      this.setData({ captchaId: d.captcha_id, captchaImg: d.image_base64 || '' });

    } catch (e) {

      wx.showToast({ title: String(e), icon: 'none' });

    }

  },



  onPhone(e) { this.setData({ phone: e.detail.value }); },

  onClub(e) { this.setData({ clubName: e.detail.value }); },

  onPwd(e) { this.setData({ password: e.detail.value }); },

  onConfirm(e) { this.setData({ confirm: e.detail.value }); },

  onCaptcha(e) { this.setData({ captchaCode: e.detail.value }); },



  async onSubmit() {

    if (this.data.submitting) return;

    this.setData({ submitting: true });

    try {

      await publicApi.submitApply({

        phone: this.data.phone,

        club_name: this.data.clubName,

        password: this.data.password,

        confirm_password: this.data.confirm,

        captcha_id: this.data.captchaId,

        captcha_code: this.data.captchaCode,

      });

      wx.showModal({

        title: '提交成功',

        content: '请等待总后台审核。通过后请使用手机号+密码登录，并在30天内保持至少一次管理操作。',

        showCancel: false,

        success: () => wx.navigateBack({ delta: 1 }),

      });

    } catch (e) {

      wx.showToast({ title: String(e), icon: 'none' });

      this.loadCaptcha();

    } finally {

      this.setData({ submitting: false });

    }

  },

});


